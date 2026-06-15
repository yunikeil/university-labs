package com.promoit.otp.dao;

import com.promoit.otp.model.Role;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import java.util.*;

@Repository
public class UserDao {
    private final JdbcTemplate jdbc;
    public UserDao(JdbcTemplate jdbc) { this.jdbc = jdbc; }
    public int create(String u, String p, Role r, String email, String phone, String tg) {
        return jdbc.update("INSERT INTO users(username,password_hash,role,email,phone,telegram_chat_id) VALUES (?,?,?,?,?,?)",u,p,r.name(),email,phone,tg);
    }
    public Map<String,Object> findByUsername(String username){
        var list=jdbc.queryForList("SELECT * FROM users WHERE username=?",username);
        return list.isEmpty()?null:list.getFirst();
    }
    public boolean adminExists(){return Boolean.TRUE.equals(jdbc.queryForObject("SELECT EXISTS(SELECT 1 FROM users WHERE role='ADMIN')",Boolean.class));}
    public List<Map<String,Object>> findAllUsers(){return jdbc.queryForList("SELECT id,username,role,email,phone,telegram_chat_id FROM users WHERE role<>'ADMIN'");}
    public int deleteUser(long id){return jdbc.update("DELETE FROM users WHERE id=?",id);}    
}
