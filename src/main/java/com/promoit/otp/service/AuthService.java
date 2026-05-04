package com.promoit.otp.service;

import com.promoit.otp.dao.UserDao;
import com.promoit.otp.dto.Dtos;
import com.promoit.otp.model.Role;
import com.promoit.otp.security.JwtService;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {
    private final UserDao userDao; private final JwtService jwt; private final JavaMailSender mailSender;
    private final BCryptPasswordEncoder enc = new BCryptPasswordEncoder();
    public AuthService(UserDao userDao, JwtService jwt, JavaMailSender mailSender){this.userDao=userDao;this.jwt=jwt;this.mailSender=mailSender;}
    public void register(Dtos.RegisterRequest r){
        String roleRaw = (r.role() == null || r.role().isBlank()) ? "ADMIN" : r.role();
        var role=Role.valueOf(roleRaw.toUpperCase());
        if(role==Role.ADMIN && userDao.adminExists()) throw new IllegalArgumentException("Admin already exists");
        String email = (r.email() == null || r.email().isBlank()) ? "demo@mailhog.local" : r.email();
        String phone = (r.phone() == null || r.phone().isBlank()) ? "none" : r.phone();
        String telegram = (r.telegramChatId() == null || r.telegramChatId().isBlank()) ? "none" : r.telegramChatId();
        userDao.create(r.username(), enc.encode(r.password()), role, email, phone, telegram);
        sendRegistrationEmail(email, r.username(), role.name());

    }
    private void sendRegistrationEmail(String email, String username, String role) {
        SimpleMailMessage msg = new SimpleMailMessage();
        msg.setFrom("noreply@otp.local");
        msg.setTo(email);
        msg.setSubject("Регистрация в OTP-сервисе");
        msg.setText("Привет, "+username+"! Регистрация прошла успешно. Ваша роль: "+role+".\n\nЭто автоматическое письмо от OTP-сервиса.");
        mailSender.send(msg);
    }

    public String login(Dtos.LoginRequest r){
        var u=userDao.findByUsername(r.username()); if(u==null||!enc.matches(r.password(), (String)u.get("password_hash"))) throw new IllegalArgumentException("Bad credentials");
        return jwt.issue(r.username(),(String)u.get("role"));
    }
}
