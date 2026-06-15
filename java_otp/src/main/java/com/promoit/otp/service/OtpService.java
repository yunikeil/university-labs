package com.promoit.otp.service;

import com.promoit.otp.dao.OtpDao;
import com.promoit.otp.dao.UserDao;
import com.promoit.otp.model.OtpStatus;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.util.Map;
import java.util.Random;

@Service
public class OtpService {
    private final OtpDao otpDao; private final UserDao userDao; private final JavaMailSender mail;
    private final RestTemplate restTemplate = new RestTemplate();
    @Value("${otp.file-path}") private String filePath;
    @Value("${otp.smpp-url}") private String smppUrl;
    @Value("${otp.telegram-bot-token}") private String bot;
    public OtpService(OtpDao otpDao, UserDao userDao, JavaMailSender mail){this.otpDao=otpDao;this.userDao=userDao;this.mail=mail;}
    public String generate(String username, String operationId, String channel) throws Exception {
        var u=userDao.findByUsername(username);
        int len=(Integer)otpDao.getConfig().get("code_length"); int ttl=(Integer)otpDao.getConfig().get("ttl_seconds");
        String code=String.format("%0"+len+"d",new Random().nextInt((int)Math.pow(10,len)));
        otpDao.create(((Number)u.get("id")).longValue(),operationId,code, LocalDateTime.now().plusSeconds(ttl));
        send(channel, u, code, operationId);
        return "OTP generated";
    }
    private void send(String ch, Map<String,Object> u, String code, String op) throws Exception {
        String msg="OTP for operation "+op+": "+code;
        switch (ch.toUpperCase()) {
            case "EMAIL" -> { var m=new SimpleMailMessage(); m.setTo((String)u.get("email")); m.setSubject("OTP code"); m.setText(msg); mail.send(m); }
            case "SMS" -> restTemplate.postForObject(smppUrl, Map.of("phone",u.get("phone"),"text",msg), String.class);
            case "TELEGRAM" -> restTemplate.getForObject("https://api.telegram.org/bot"+bot+"/sendMessage?chat_id="+u.get("telegram_chat_id")+"&text="+msg, String.class);
            case "FILE" -> Files.writeString(Path.of(filePath),msg+System.lineSeparator(), java.nio.file.StandardOpenOption.CREATE, java.nio.file.StandardOpenOption.APPEND);
            default -> throw new IllegalArgumentException("Unknown channel");
        }
    }
    public boolean validate(String username, String operationId, String code){
        var u=userDao.findByUsername(username); var otp=otpDao.activeCode(((Number)u.get("id")).longValue(),operationId); if(otp==null) return false;
        if(LocalDateTime.now().isAfter(((java.sql.Timestamp)otp.get("expires_at")).toLocalDateTime())) return false;
        if(!code.equals(otp.get("code"))) return false;
        otpDao.markUsed(((Number)otp.get("id")).longValue());
        return true;
    }
    public int expire(){ return otpDao.markExpired(); }
    public Map<String,Object> config(){return otpDao.getConfig();}
    public void updateConfig(int len, int ttl){otpDao.updateConfig(len,ttl);}    
}
