package com.promoit.otp.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

@Configuration
public class Beans {
    @Bean
    BCryptPasswordEncoder passwordEncoder(){ return new BCryptPasswordEncoder(); }
}
