package com.promoit.otp.controller;

import com.promoit.otp.dao.UserDao;
import com.promoit.otp.dto.Dtos;
import com.promoit.otp.service.OtpService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/admin")
@Tag(name = "Администрирование", description = "Методы администратора для управления конфигурацией OTP и пользователями")
@SecurityRequirement(name = "bearerAuth")
public class AdminController {
    private final OtpService otp; private final UserDao users;
    public AdminController(OtpService otp, UserDao users){this.otp=otp;this.users=users;}

    @Operation(summary = "Изменить конфигурацию OTP", description = "Обновляет длину OTP-кода и время жизни кода (TTL в секундах)")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Конфигурация обновлена"),
            @ApiResponse(responseCode = "403", description = "Недостаточно прав")
    })
    @PutMapping("/config")
    public String update(@Valid @RequestBody Dtos.ConfigRequest req){ otp.updateConfig(req.codeLength(), req.ttlSeconds()); return "updated"; }

    @Operation(summary = "Список пользователей", description = "Возвращает список всех пользователей, кроме администраторов")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Список получен"),
            @ApiResponse(responseCode = "403", description = "Недостаточно прав")
    })
    @GetMapping("/users")
    public Object users(){ return users.findAllUsers(); }

    @Operation(summary = "Удалить пользователя", description = "Удаляет пользователя по id вместе со всеми привязанными OTP-кодами")
    @ApiResponses({
            @ApiResponse(responseCode = "200", description = "Пользователь удалён"),
            @ApiResponse(responseCode = "403", description = "Недостаточно прав")
    })
    @DeleteMapping("/users/{id}")
    public String delete(@PathVariable long id){ users.deleteUser(id); return "deleted"; }
}
