package com.promoit.otp.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

public class Dtos {
    public record RegisterRequest(
            @Schema(description = "Уникальный логин пользователя", example = "ivan.petrov")
            @NotBlank String username,
            @Schema(description = "Пароль пользователя", example = "StrongPass123")
            @NotBlank String password,
            @Schema(description = "Роль пользователя: ADMIN или USER. Если не передать, будет ADMIN", example = "ADMIN")
            String role,
            @Schema(description = "Email для отправки OTP", example = "demo@mailhog.local")
            String email,
            @Schema(description = "Телефон для отправки OTP по SMS", example = "none")
            String phone,
            @Schema(description = "ID чата Telegram для отправки OTP", example = "none")
            String telegramChatId) {}

    public record LoginRequest(
            @Schema(description = "Логин пользователя", example = "ivan.petrov")
            @NotBlank String username,
            @Schema(description = "Пароль пользователя", example = "StrongPass123")
            @NotBlank String password) {}

    public record OAuthTokenResponse(
            @Schema(description = "OAuth2 access token (JWT)", example = "eyJhbGciOiJIUzI1NiJ9...")
            String access_token,
            @Schema(description = "Тип токена", example = "Bearer")
            String token_type,
            @Schema(description = "Время жизни токена в секундах", example = "3600")
            long expires_in) {}

    public record TokenResponse(
            @Schema(description = "JWT токен доступа", example = "eyJhbGciOiJIUzI1NiJ9...")
            String token) {}

    public record ConfigRequest(
            @Schema(description = "Длина OTP-кода", example = "6", minimum = "4", maximum = "10")
            @NotNull Integer codeLength,
            @Schema(description = "Время жизни OTP в секундах", example = "300", minimum = "30", maximum = "3600")
            @NotNull Integer ttlSeconds) {}

    public record OtpCreateRequest(
            @Schema(description = "Идентификатор бизнес-операции", example = "payment-2026-0001")
            @NotBlank String operationId,
            @Schema(description = "Канал отправки OTP: EMAIL, SMS, TELEGRAM, FILE", example = "EMAIL")
            @NotBlank String channel) {}

    public record OtpValidateRequest(
            @Schema(description = "Идентификатор операции, для которой проверяется OTP", example = "payment-2026-0001")
            @NotBlank String operationId,
            @Schema(description = "OTP код, полученный пользователем", example = "123456")
            @NotBlank String code) {}
}
