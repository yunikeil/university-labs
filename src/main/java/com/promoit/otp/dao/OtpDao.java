package com.promoit.otp.dao;

import com.promoit.otp.model.OtpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import java.time.LocalDateTime;
import java.util.Map;

@Repository
public class OtpDao {
    private final JdbcTemplate jdbc;
    public OtpDao(JdbcTemplate jdbc){this.jdbc=jdbc;}
    public Map<String,Object> getConfig(){ return jdbc.queryForMap("SELECT code_length, ttl_seconds FROM otp_config WHERE id=1"); }
    public void updateConfig(int len,int ttl){ jdbc.update("UPDATE otp_config SET code_length=?, ttl_seconds=?, updated_at=NOW() WHERE id=1",len,ttl); }
    public void create(long userId,String op,String code, LocalDateTime exp){jdbc.update("INSERT INTO otp_codes(user_id,operation_id,code,status,expires_at) VALUES (?,?,?,?,?)",userId,op,code,OtpStatus.ACTIVE.name(),exp);}
    public Map<String,Object> activeCode(long userId,String op){var l=jdbc.queryForList("SELECT * FROM otp_codes WHERE user_id=? AND operation_id=? AND status='ACTIVE' ORDER BY created_at DESC LIMIT 1",userId,op);return l.isEmpty()?null:l.getFirst();}
    public void markUsed(long id){jdbc.update("UPDATE otp_codes SET status='USED' WHERE id=?",id);}    
    public int markExpired(){return jdbc.update("UPDATE otp_codes SET status='EXPIRED' WHERE status='ACTIVE' AND expires_at < NOW()");}
}
