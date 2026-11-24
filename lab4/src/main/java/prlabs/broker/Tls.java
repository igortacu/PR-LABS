package prlabs.broker;

import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyStore;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import javax.net.ssl.KeyManagerFactory;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;

/** TLS helpers, so that tokens and messages never travel in clear text. */
final class Tls {
    private Tls() {}

    /** The broker's private key and certificate, from the keystore that make-cert.sh creates. */
    static KeyManagerFactory keyManagers(Path keystore) throws Exception {
        String password = System.getenv("KEYSTORE_PASSWORD");
        if (password == null || password.isEmpty())
            throw new IllegalStateException("Set KEYSTORE_PASSWORD to the password of " + keystore);
        KeyStore store = KeyStore.getInstance("PKCS12");
        try (InputStream input = Files.newInputStream(keystore)) { store.load(input, password.toCharArray()); }
        KeyManagerFactory factory = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
        factory.init(store, password.toCharArray());
        return factory;
    }

    static SSLContext serverContext(Path keystore) throws Exception {
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(keyManagers(keystore).getKeyManagers(), null, null);
        return context;
    }

    /** A client context that trusts only the broker's certificate (broker.crt). */
    static SSLContext clientContext(Path certificate) throws Exception {
        Certificate broker;
        try (InputStream input = Files.newInputStream(certificate)) {
            broker = CertificateFactory.getInstance("X.509").generateCertificate(input);
        }
        KeyStore store = KeyStore.getInstance("PKCS12");
        store.load(null, null);
        store.setCertificateEntry("broker", broker);
        TrustManagerFactory factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        factory.init(store);
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, factory.getTrustManagers(), null);
        return context;
    }

    /** Publishers read their token from BROKER_TOKEN, so it does not show up in `ps`. */
    static String token() {
        String token = System.getenv("BROKER_TOKEN");
        if (token == null || token.isBlank()) throw new IllegalStateException("Set BROKER_TOKEN to your token");
        return token;
    }
}
