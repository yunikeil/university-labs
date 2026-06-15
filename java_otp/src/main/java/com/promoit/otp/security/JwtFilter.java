package com.promoit.otp.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import java.io.IOException;
import java.util.List;

@Component
public class JwtFilter extends OncePerRequestFilter {
    private final JwtService jwt;
    public JwtFilter(JwtService jwt){this.jwt=jwt;}
    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain) throws ServletException, IOException {
        var h=request.getHeader("Authorization");
        if(h!=null){
            String token = h.startsWith("Bearer ") ? h.substring(7) : h.trim();
            if (!token.isBlank()) {
            try {
                var c=jwt.parse(token);
                var auth = new UsernamePasswordAuthenticationToken(c.getSubject(), null, List.of(new SimpleGrantedAuthority("ROLE_"+c.get("role",String.class))));
                SecurityContextHolder.getContext().setAuthentication(auth);
            } catch (Exception ignored) {}
            }
        }
        filterChain.doFilter(request,response);
    }
}
