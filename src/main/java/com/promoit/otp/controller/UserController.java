package com.promoit.otp.controller;

import com.promoit.otp.dto.Dtos;
import com.promoit.otp.service.OtpService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/otp")
@Tag(name = "OTP операции", description = "Генерация и проверка одноразовых кодов для операций пользователя")
@SecurityRequirement(name = "bearerAuth")
public class UserController {
    private final OtpService otp;
    public UserController(OtpService otp){this.otp=otp;}

    @Operation(summary = "Сгенерировать OTP", description = "Создаёт OTP для operationId и отправляет его через выбранный канал: EMAIL, SMS, TELEGRAM или FILE")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "OTP успешно создан и отправлен"),
            @ApiResponse(responseCode = "400", description = "Некорректный канал или данные")
    })
    @PostMapping("/generate")
    public String gen(Authentication auth, @Valid @RequestBody Dtos.OtpCreateRequest req) throws Exception { return otp.generate(auth.getName(), req.operationId(), req.channel()); }

    @Operation(summary = "Проверить OTP", description = "Проверяет OTP-код для operationId. При успешной проверке код становится USED")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Возвращает valid или invalid"),
            @ApiResponse(responseCode = "400", description = "Некорректный запрос")
    })
    @PostMapping("/validate")
    public String val(Authentication auth, @Valid @RequestBody Dtos.OtpValidateRequest req) { return otp.validate(auth.getName(), req.operationId(), req.code()) ? "valid" : "invalid"; }
}
