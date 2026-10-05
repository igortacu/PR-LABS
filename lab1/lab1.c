/*
 * Lab 1 - Concurrency in practice (C, POSIX threads).
 *
 *   lab1 gen   <out> [count=50000000] [seed=42]   generate numbers file
 *   lab1 split <in> <outdir> [parts=8]            split into numbers_1..N.txt
 *   lab1 1a    <file> <threads>                   Task 1a
 *   lab1 1b    <file> <unsync|mutex|local> [threads=logical CPUs]   Task 1b
 *   lab1 1c    <file> <workers> [batch=10000] [qcap=100]   Task 1c (qcap 0 = unbounded)
 *   lab1 2     <dir> <threads> [nocache]          Task 2 (files numbers_1..8.txt)
 *   lab1 cpus                                     print logical CPU count
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

typedef struct { long long neg, pos, zero; } counts_t;

static double now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1e3 + ts.tv_nsec / 1e6;
}

static double peak_mb(void) {
    struct rusage ru;
    getrusage(RUSAGE_SELF, &ru);
#ifdef __APPLE__
    return ru.ru_maxrss / 1048576.0; /* bytes on macOS */
#else
    return ru.ru_maxrss / 1024.0;    /* KiB on Linux */
#endif
}

static void die(const char *msg) { perror(msg); exit(1); }

static void print_result(const char *task, const char *variant, int threads,
                         double ms, const counts_t *c, const char *extra) {
    printf("RESULT task=%s variant=%s threads=%d time_ms=%.1f peak_mb=%.1f "
           "neg=%lld pos=%lld zero=%lld total=%lld %s\n",
           task, variant, threads, ms, peak_mb(), c->neg, c->pos, c->zero,
           c->neg + c->pos + c->zero, extra ? extra : "");
}

/* Parse every line in [p,end) and update counters. Lines are "[-]digits\n". */
static void count_buf(const char *p, const char *end, counts_t *c) {
    while (p < end) {
        if (*p == '\n' || *p == '\r') { p++; continue; }
        int neg = 0, digits = 0;
        long v = 0;
        if (*p == '-') { neg = 1; p++; }
        while (p < end && *p >= '0' && *p <= '9') { v = v * 10 + (*p - '0'); p++; digits++; }
        while (p < end && *p != '\n') p++;
        if (!digits) continue;
        if (v == 0) c->zero++;
        else if (neg) c->neg++;
        else c->pos++;
    }
}

/* ------------------------------------------------------------------ gen/split */

static uint64_t splitmix64(uint64_t *s) {
    uint64_t z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static int cmd_gen(const char *out, long long count, uint64_t seed) {
    FILE *f = fopen(out, "w");
    if (!f) die("fopen");
    static char buf[1 << 20];
    setvbuf(f, buf, _IOFBF, sizeof buf);
    counts_t c = {0, 0, 0};
    for (long long i = 0; i < count; i++) {
        long v = (long)(splitmix64(&seed) % 2000001ULL) - 1000000L;
        fprintf(f, "%ld\n", v);
        if (v < 0) c.neg++; else if (v > 0) c.pos++; else c.zero++;
    }
    fclose(f);
    printf("generated %lld numbers: neg=%lld pos=%lld zero=%lld total=%lld\n",
           count, c.neg, c.pos, c.zero, c.neg + c.pos + c.zero);
    return 0;
}

static int cmd_split(const char *in, const char *dir, int parts) {
    FILE *f = fopen(in, "r");
    if (!f) die("fopen in");
    long long total = 0;
    char line[64];
    /* first pass: count lines */
    while (fgets(line, sizeof line, f)) total++;
    rewind(f);
    long long per = total / parts;
    for (int p = 0; p < parts; p++) {
        char name[1024];
        snprintf(name, sizeof name, "%s/numbers_%d.txt", dir, p + 1);
        FILE *o = fopen(name, "w");
        if (!o) die("fopen out");
        long long n = (p == parts - 1) ? total - per * (parts - 1) : per;
        for (long long i = 0; i < n && fgets(line, sizeof line, f); i++) fputs(line, o);
        fclose(o);
        printf("wrote %s (%lld lines)\n", name, n);
    }
    fclose(f);
    return 0;
}

/* ------------------------------------------------------------------ Task 1a */

typedef struct { int fd; off_t size; int idx, nthreads; counts_t c; } a_arg;

/* First line start >= b (b itself if the previous byte is '\n'). */
static off_t line_boundary(int fd, off_t size, off_t b) {
    if (b <= 0) return 0;
    if (b >= size) return size;
    char buf[4096];
    off_t pos = b - 1;
    for (;;) {
        ssize_t n = pread(fd, buf, sizeof buf, pos);
        if (n <= 0) return size;
        for (ssize_t i = 0; i < n; i++)
            if (buf[i] == '\n') return pos + i + 1;
        pos += n;
    }
}

static void process_range(int fd, off_t start, off_t end, counts_t *c) {
    enum { BUF = 1 << 20 };
    char *buf = malloc(BUF + 16);
    if (!buf) die("malloc");
    size_t carry = 0;
    off_t pos = start;
    while (pos < end) {
        size_t want = BUF - carry;
        if ((off_t)want > end - pos) want = (size_t)(end - pos);
        ssize_t n = pread(fd, buf + carry, want, pos);
        if (n <= 0) break;
        pos += n;
        size_t len = carry + (size_t)n, keep = len;
        if (pos < end)
            while (keep > 0 && buf[keep - 1] != '\n') keep--;
        count_buf(buf, buf + keep, c);
        carry = len - keep;
        memmove(buf, buf + keep, carry);
    }
    if (carry) count_buf(buf, buf + carry, c);
    free(buf);
}

static void *a_worker(void *p) {
    a_arg *a = p;
    off_t s = line_boundary(a->fd, a->size, a->size * a->idx / a->nthreads);
    off_t e = line_boundary(a->fd, a->size, a->size * (a->idx + 1) / a->nthreads);
    process_range(a->fd, s, e, &a->c);
    return NULL;
}

static int cmd_1a(const char *file, int T) {
    int fd = open(file, O_RDONLY);
    if (fd < 0) die("open");
    struct stat st;
    fstat(fd, &st);
    pthread_t *th = malloc(sizeof *th * T);
    a_arg *args = calloc(T, sizeof *args);
    double t0 = now_ms();
    for (int i = 0; i < T; i++) {
        args[i] = (a_arg){.fd = fd, .size = st.st_size, .idx = i, .nthreads = T};
        pthread_create(&th[i], NULL, a_worker, &args[i]);
    }
    counts_t c = {0, 0, 0};
    for (int i = 0; i < T; i++) {
        pthread_join(th[i], NULL);
        c.neg += args[i].c.neg; c.pos += args[i].c.pos; c.zero += args[i].c.zero;
    }
    double ms = now_ms() - t0;
    print_result("1a", "split-file", T, ms, &c, "");
    return 0;
}

/* ------------------------------------------------------------------ Task 1b */

static int *load_array(const char *file, long long *n_out) {
    int fd = open(file, O_RDONLY);
    if (fd < 0) die("open");
    long long cap = 1 << 20, n = 0;
    int *arr = malloc(cap * sizeof *arr);
    enum { BUF = 1 << 20 };
    char *buf = malloc(BUF + 16);
    size_t carry = 0;
    ssize_t r;
    while ((r = read(fd, buf + carry, BUF - carry)) > 0) {
        size_t len = carry + (size_t)r, keep = len;
        while (keep > 0 && buf[keep - 1] != '\n') keep--;
        const char *p = buf, *end = buf + keep;
        while (p < end) {
            int neg = 0, digits = 0; long v = 0;
            if (*p == '-') { neg = 1; p++; }
            while (p < end && *p >= '0' && *p <= '9') { v = v * 10 + (*p - '0'); p++; digits++; }
            while (p < end && *p != '\n') p++;
            p++;
            if (!digits) continue;
            if (n == cap) { cap *= 2; arr = realloc(arr, cap * sizeof *arr); }
            arr[n++] = (int)(neg ? -v : v);
        }
        carry = len - keep;
        memmove(buf, buf + keep, carry);
    }
    free(buf);
    close(fd);
    *n_out = n;
    return arr;
}

static const int *g_arr;
static long long g_n;
static int g_T;
/* volatile forces a real load/add/store per increment, so the race is not
 * optimised away into a register by the compiler. */
static volatile long long g_neg, g_pos, g_zero;
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;

typedef struct { int idx; counts_t c; } b_arg;

static void *b_unsync(void *p) {
    b_arg *a = (b_arg *)p;
    long long s = g_n * a->idx / g_T, e = g_n * (a->idx + 1) / g_T;
    for (long long i = s; i < e; i++) {
        int v = g_arr[i];
        if (v < 0) g_neg++; else if (v > 0) g_pos++; else g_zero++;
    }
    return NULL;
}

static void *b_mutex(void *p) {
    b_arg *a = (b_arg *)p;
    long long s = g_n * a->idx / g_T, e = g_n * (a->idx + 1) / g_T;
    for (long long i = s; i < e; i++) {
        int v = g_arr[i];
        pthread_mutex_lock(&g_mu);
        if (v < 0) g_neg++; else if (v > 0) g_pos++; else g_zero++;
        pthread_mutex_unlock(&g_mu);
    }
    return NULL;
}

static void *b_local(void *p) {
    b_arg *a = (b_arg *)p;
    long long s = g_n * a->idx / g_T, e = g_n * (a->idx + 1) / g_T;
    long long neg = 0, pos = 0, zero = 0;
    for (long long i = s; i < e; i++) {
        int v = g_arr[i];
        if (v < 0) neg++; else if (v > 0) pos++; else zero++;
    }
    a->c = (counts_t){neg, pos, zero};
    return NULL;
}

static int cmd_1b(const char *file, const char *ver, int T) {
    void *(*fn)(void *);
    if (!strcmp(ver, "unsync")) fn = b_unsync;
    else if (!strcmp(ver, "mutex")) fn = b_mutex;
    else if (!strcmp(ver, "local")) fn = b_local;
    else { fprintf(stderr, "unknown version %s\n", ver); return 2; }

    g_arr = load_array(file, &g_n); /* not measured */
    g_T = T;
    pthread_t *th = malloc(sizeof *th * T);
    b_arg *args = calloc(T, sizeof *args);
    double t0 = now_ms();
    for (int i = 0; i < T; i++) { args[i].idx = i; pthread_create(&th[i], NULL, fn, &args[i]); }
    for (int i = 0; i < T; i++) pthread_join(th[i], NULL);
    counts_t c;
    if (fn == b_local) {
        c = (counts_t){0, 0, 0};
        for (int i = 0; i < T; i++) { c.neg += args[i].c.neg; c.pos += args[i].c.pos; c.zero += args[i].c.zero; }
    } else {
        c = (counts_t){g_neg, g_pos, g_zero};
    }
    double ms = now_ms() - t0;
    print_result("1b", ver, T, ms, &c, "");
    return 0;
}

/* ------------------------------------------------------------------ Task 1c */

typedef struct batch { char *data; size_t len; struct batch *next; } batch_t;

typedef struct {
    batch_t *head, *tail;
    long count, cap, maxcount;
    int closed;
    pthread_mutex_t mu;
    pthread_cond_t not_full, not_empty;
} queue_t;

static queue_t Q;

static void q_push(batch_t *b) {
    pthread_mutex_lock(&Q.mu);
    while (Q.cap > 0 && Q.count >= Q.cap) pthread_cond_wait(&Q.not_full, &Q.mu);
    b->next = NULL;
    if (Q.tail) Q.tail->next = b; else Q.head = b;
    Q.tail = b;
    if (++Q.count > Q.maxcount) Q.maxcount = Q.count;
    pthread_cond_signal(&Q.not_empty);
    pthread_mutex_unlock(&Q.mu);
}

static void q_close(void) {
    pthread_mutex_lock(&Q.mu);
    Q.closed = 1;
    pthread_cond_broadcast(&Q.not_empty);
    pthread_mutex_unlock(&Q.mu);
}

static batch_t *q_pop(void) {
    pthread_mutex_lock(&Q.mu);
    while (!Q.head && !Q.closed) pthread_cond_wait(&Q.not_empty, &Q.mu);
    batch_t *b = Q.head;
    if (b) {
        Q.head = b->next;
        if (!Q.head) Q.tail = NULL;
        Q.count--;
        pthread_cond_signal(&Q.not_full);
    }
    pthread_mutex_unlock(&Q.mu);
    return b;
}

static void *c_worker(void *p) {
    counts_t *c = p;
    batch_t *b;
    while ((b = q_pop())) {
        count_buf(b->data, b->data + b->len, c);
        free(b->data);
        free(b);
    }
    return NULL;
}

static int cmd_1c(const char *file, int W, int batch_lines, long qcap) {
    FILE *f = fopen(file, "r");
    if (!f) die("fopen");
    memset(&Q, 0, sizeof Q);
    pthread_mutex_init(&Q.mu, NULL);
    pthread_cond_init(&Q.not_full, NULL);
    pthread_cond_init(&Q.not_empty, NULL);
    Q.cap = qcap;

    pthread_t *th = malloc(sizeof *th * W);
    counts_t *cs = calloc(W, sizeof *cs);
    double t0 = now_ms();
    for (int i = 0; i < W; i++) pthread_create(&th[i], NULL, c_worker, &cs[i]);

    /* the calling thread is the reader */
    long long read_lines = 0;
    int eof = 0;
    while (!eof) {
        size_t cap = (size_t)batch_lines * 12 + 64, len = 0;
        batch_t *b = malloc(sizeof *b);
        b->data = malloc(cap);
        int n = 0;
        while (n < batch_lines) {
            if (cap - len < 64) { cap *= 2; b->data = realloc(b->data, cap); }
            if (!fgets(b->data + len, 64, f)) { eof = 1; break; }
            len += strlen(b->data + len);
            n++;
        }
        read_lines += n;
        b->len = len;
        if (n > 0) q_push(b); else { free(b->data); free(b); }
    }
    q_close();

    counts_t c = {0, 0, 0};
    for (int i = 0; i < W; i++) {
        pthread_join(th[i], NULL);
        c.neg += cs[i].neg; c.pos += cs[i].pos; c.zero += cs[i].zero;
    }
    double ms = now_ms() - t0;
    char extra[128];
    snprintf(extra, sizeof extra, "batch=%d qcap=%ld maxq=%ld read_lines=%lld", batch_lines, qcap, Q.maxcount, read_lines);
    print_result("1c", "producer-consumer", W, ms, &c, extra);
    fclose(f);
    return 0;
}

/* ------------------------------------------------------------------ Task 2 */

typedef struct { const char *dir; int idx, nthreads, nfiles, nocache; counts_t c; } t2_arg;

static void *t2_worker(void *p) {
    t2_arg *a = p;
    for (int i = a->idx; i < a->nfiles; i += a->nthreads) {
        char name[1024];
        snprintf(name, sizeof name, "%s/numbers_%d.txt", a->dir, i + 1);
        int fd = open(name, O_RDONLY);
        if (fd < 0) die(name);
#ifdef F_NOCACHE
        if (a->nocache) fcntl(fd, F_NOCACHE, 1);
#endif
        struct stat st;
        fstat(fd, &st);
        char *buf = malloc((size_t)st.st_size + 1);   /* one byte buffer per file */
        if (!buf) die("malloc");
        size_t got = 0;
        while (got < (size_t)st.st_size) {              /* a single read(2), repeated only if the OS returns short */
            ssize_t r = read(fd, buf + got, (size_t)st.st_size - got);
            if (r <= 0) die("read");
            got += (size_t)r;
        }
        close(fd);
        count_buf(buf, buf + got, &a->c);
        free(buf);
    }
    return NULL;
}

static int cmd_2(const char *dir, int T, int nocache) {
    const int nfiles = 8;
    pthread_t *th = malloc(sizeof *th * T);
    t2_arg *args = calloc(T, sizeof *args);
    double t0 = now_ms();
    for (int i = 0; i < T; i++) {
        args[i] = (t2_arg){.dir = dir, .idx = i, .nthreads = T, .nfiles = nfiles, .nocache = nocache};
        pthread_create(&th[i], NULL, t2_worker, &args[i]);
    }
    counts_t c = {0, 0, 0};
    for (int i = 0; i < T; i++) {
        pthread_join(th[i], NULL);
        c.neg += args[i].c.neg; c.pos += args[i].c.pos; c.zero += args[i].c.zero;
    }
    double ms = now_ms() - t0;
    print_result("2", "files", T, ms, &c, "");
    return 0;
}

/* ------------------------------------------------------------------ main */

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: see header of lab1.c\n"); return 2; }
    const char *cmd = argv[1];
    if (!strcmp(cmd, "cpus")) { printf("%ld\n", sysconf(_SC_NPROCESSORS_ONLN)); return 0; }
    if (!strcmp(cmd, "gen") && argc >= 3)
        return cmd_gen(argv[2], argc > 3 ? atoll(argv[3]) : 50000000LL, argc > 4 ? strtoull(argv[4], 0, 10) : 42);
    if (!strcmp(cmd, "split") && argc >= 4) return cmd_split(argv[2], argv[3], argc > 4 ? atoi(argv[4]) : 8);
    if (!strcmp(cmd, "1a") && argc >= 4) return cmd_1a(argv[2], atoi(argv[3]));
    if (!strcmp(cmd, "1b") && argc >= 4)
        return cmd_1b(argv[2], argv[3], argc > 4 ? atoi(argv[4]) : (int)sysconf(_SC_NPROCESSORS_ONLN));
    if (!strcmp(cmd, "1c") && argc >= 4)
        return cmd_1c(argv[2], atoi(argv[3]), argc > 4 ? atoi(argv[4]) : 10000, argc > 5 ? atol(argv[5]) : 100);
    if (!strcmp(cmd, "2") && argc >= 4)
        return cmd_2(argv[2], atoi(argv[3]), argc > 4 && !strcmp(argv[4], "nocache"));
    fprintf(stderr, "bad arguments, see header of lab1.c\n");
    return 2;
}
