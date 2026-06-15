package com.promoit.otp.service;

import com.promoit.otp.dao.UserDao;
import com.promoit.otp.dto.Dtos;
import com.promoit.otp.security.JwtService;
import org.springframework.mail.javamail.JavaMailSender;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class AuthServiceTest {
    @Mock UserDao userDao;
    @Mock JwtService jwtService;
    @Mock JavaMailSender mailSender;
    @InjectMocks AuthService authService;

    @Test
    void shouldRejectSecondAdmin() {
        when(userDao.adminExists()).thenReturn(true);
        var req = new Dtos.RegisterRequest("a","p","ADMIN",null,null,null);
        assertThatThrownBy(() -> authService.register(req)).isInstanceOf(IllegalArgumentException.class);
    }


    @Test
    void shouldUseAdminRoleByDefaultWhenRoleIsEmpty() {
        when(userDao.adminExists()).thenReturn(false);
        var req = new Dtos.RegisterRequest("u2","p2","",null,null,null);
        authService.register(req);
        verify(userDao).create(eq("u2"), anyString(), eq(com.promoit.otp.model.Role.ADMIN), eq("demo@mailhog.local"), eq("none"), eq("none"));
        verify(mailSender).send(any(org.springframework.mail.SimpleMailMessage.class));
    }

    @Test
    void shouldLoginAndReturnToken() {
        String hash = new org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder().encode("pass");
        when(userDao.findByUsername("u")).thenReturn(Map.of("password_hash", hash, "role", "USER"));
        when(jwtService.issue("u", "USER")).thenReturn("token");
        String token = authService.login(new Dtos.LoginRequest("u", "pass"));
        assertThat(token).isEqualTo("token");
        verify(jwtService).issue("u", "USER");
    }
}
