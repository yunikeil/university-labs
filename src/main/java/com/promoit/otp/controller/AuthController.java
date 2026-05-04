package com.promoit.otp.controller;

import com.promoit.otp.dto.Dtos;
import com.promoit.otp.service.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;


@RestController
@RequestMapping("/auth")
@Tag(name = "Аутентификация", description = "Регистрация пользователей и получение JWT-токена")
public class AuthController {
    private final AuthService service;
    public AuthController(AuthService service){this.service=service;}

    @Operation(summary = "Регистрация нового пользователя", description = "Создаёт пользователя с ролью USER или ADMIN (в системе может быть только один ADMIN)")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Пользователь успешно зарегистрирован"),
            @ApiResponse(responseCode = "400", description = "Ошибка валидации или второй ADMIN")
    })
    @PostMapping("/register")
    public String register(@Valid @org.springframework.web.bind.annotation.RequestBody Dtos.RegisterRequest request){ service.register(request); return "registered"; }

    @Operation(summary = "Вход пользователя", description = "Проверяет логин/пароль и возвращает JWT-токен с ограниченным сроком действия")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Токен успешно выдан"),
            @ApiResponse(responseCode = "400", description = "Некорректные учётные данные")
    })
    @PostMapping("/login")
    public Dtos.TokenResponse login(@Valid @org.springframework.web.bind.annotation.RequestBody Dtos.LoginRequest request){ return new Dtos.TokenResponse(service.login(request)); }

    @Operation(summary = "Проверка авторизации", description = "Пустой технический endpoint для проверки, что JWT принят и авторизация работает")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Токен валиден"),
            @ApiResponse(responseCode = "401", description = "Токен отсутствует или невалиден")
    })
    @GetMapping("/check")
    public Dtos.TokenResponse check(Authentication auth){ return new Dtos.TokenResponse("ok:" + auth.getName()); }

}

