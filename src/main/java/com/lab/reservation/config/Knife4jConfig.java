package com.lab.reservation.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import io.swagger.v3.oas.models.security.SecurityRequirement;
import io.swagger.v3.oas.models.security.SecurityScheme;
import io.swagger.v3.oas.models.Components;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class Knife4jConfig {
    @Bean
    public OpenAPI openAPI() {
        return new OpenAPI()
            .info(new Info().title("实验室设备预约 API").version("v1").description("高校实验室设备智能预约与管控平台 - 阶段1 后端"))
            .addSecurityItem(new SecurityRequirement().addList("Bearer"))
            .components(new Components().addSecuritySchemes("Bearer",
                new SecurityScheme().type(SecurityScheme.Type.HTTP).scheme("bearer").bearerFormat("JWT")
                    .in(SecurityScheme.In.HEADER).name("Authorization")));
    }
}
