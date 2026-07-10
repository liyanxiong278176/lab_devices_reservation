package com.lab.reservation.ai.config;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class CryptoUtilTest {

    // IMPORTANT: must decode to EXACTLY 32 bytes (constructor enforces 32).
    // "0123456789abcdef0123456789abcdef" = 32 ASCII bytes.
    private final CryptoUtil util = new CryptoUtil("MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=");

    @Test
    void encryptDecryptRoundTrip() {
        String plain = "sk-abcdef123456";
        String cipher = util.encrypt(plain);
        assertNotEquals(plain, cipher);
        assertEquals(plain, util.decrypt(cipher));
    }

    @Test
    void eachEncryptionUsesFreshIv() {
        String plain = "sk-same";
        assertNotEquals(util.encrypt(plain), util.encrypt(plain));
    }

    @Test
    void decryptGarbageReturnsNull() {
        assertNull(util.decrypt("not-valid-base64!!!"));
    }
}
