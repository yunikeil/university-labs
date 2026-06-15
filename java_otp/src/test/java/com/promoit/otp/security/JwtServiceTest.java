package com.promoit.otp.security;

import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.assertThat;

class JwtServiceTest {
    @Test
    void shouldIssueAndParseToken() {
        JwtService service = new JwtService("very-secret-key-change-it-very-secret-key-change-it", 3600);
        String token = service.issue("john", "USER");
        var claims = service.parse(token);
        assertThat(claims.getSubject()).isEqualTo("john");
        assertThat(claims.get("role", String.class)).isEqualTo("USER");
    }
}
