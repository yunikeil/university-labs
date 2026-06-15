package com.promoit.otp.scheduler;

import com.promoit.otp.service.OtpService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class OtpExpirationScheduler {
    private static final Logger log = LoggerFactory.getLogger(OtpExpirationScheduler.class);
    private final OtpService service;
    public OtpExpirationScheduler(OtpService service){this.service=service;}
    @Scheduled(fixedDelayString = "${otp.expire-interval-ms:60000}")
    public void expire(){ int updated = service.expire(); log.info("Expired OTP updated: {}", updated); }
}
