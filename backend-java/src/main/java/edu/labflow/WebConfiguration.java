package edu.labflow;

import jakarta.servlet.http.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.*;

@Configuration
public class WebConfiguration implements WebMvcConfigurer {
  private final AuthService auth;
  private final Settings settings;
  private final RateLimiter limiter;

  public WebConfiguration(AuthService auth, Settings settings, RateLimiter limiter) {
    this.auth = auth;
    this.settings = settings;
    this.limiter = limiter;
  }

  @Override
  public void addCorsMappings(CorsRegistry registry) {
    registry
        .addMapping("/api/v2/**")
        .allowedOrigins(settings.origins().toArray(String[]::new))
        .allowedMethods("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
        .allowedHeaders("Content-Type", "Idempotency-Key", "X-Request-ID", "X-CSRF-Token")
        .allowCredentials(true);
  }

  @Override
  public void addInterceptors(InterceptorRegistry registry) {
    registry
        .addInterceptor(
            new HandlerInterceptor() {
              @Override
              public boolean preHandle(
                  HttpServletRequest req, HttpServletResponse res, Object handler) {
                if (req.getDispatcherType() != jakarta.servlet.DispatcherType.REQUEST) return true;
                String rid = req.getHeader("X-Request-ID");
                if (rid == null || !rid.matches("[A-Za-z0-9_-]{1,100}"))
                  rid = UUID.randomUUID().toString();
                req.setAttribute("request_id", rid);
                res.setHeader("X-Request-ID", rid);
                if (req.getMethod().equals("OPTIONS")) return true;
                String path = req.getRequestURI();
                if (!Set.of("GET", "HEAD", "OPTIONS", "TRACE").contains(req.getMethod()))
                  csrf(req, path);
                if (!path.startsWith("/api/v2/openapi.json/")
                    && !Set.of(
                            "/api/v2/docs",
                            "/api/v2/openapi.json",
                            "/api/v2/auth/csrf",
                            "/api/v2/auth/colleges",
                            "/api/v2/auth/login",
                            "/api/v2/auth/register",
                            "/api/v2/auth/refresh",
                            "/api/v2/live",
                            "/api/v2/health",
                            "/api/v2/ready",
                            "/api/v2/metrics")
                        .contains(path)) {
                  var principal = auth.principal(req);
                  req.setAttribute("principal", principal);
                  limiter.authenticated(principal, req);
                }
                return true;
              }
            })
        .addPathPatterns("/api/v2/**");
  }

  private void csrf(HttpServletRequest req, String path) {
    String origin = req.getHeader("Origin");
    if (origin == null) {
      String ref = req.getHeader("Referer");
      if (ref != null) {
        try {
          URI uri = URI.create(ref);
          if (uri.getUserInfo() == null) origin = uri.getScheme() + "://" + uri.getAuthority();
        } catch (IllegalArgumentException e) {
        }
      }
    }
    if (!settings.origins().contains(origin))
      throw new ApiError("CSRF_ORIGIN_INVALID", "请求来源不受信任", 403);
    String cookie = auth.cookie(req, "CSRF_COOKIE_NAME", "lab_csrf"),
        header = req.getHeader("X-CSRF-Token");
    if (cookie == null
        || header == null
        || !MessageDigest.isEqual(
            cookie.getBytes(StandardCharsets.UTF_8), header.getBytes(StandardCharsets.UTF_8))
        || auth.csrfSid(cookie) == null)
      throw new ApiError("CSRF_TOKEN_INVALID", "CSRF 校验失败，请刷新页面后重试", 403);
    if (path.equals("/api/v2/auth/login") || path.equals("/api/v2/auth/register")) return;
    String sid;
    if (path.equals("/api/v2/auth/refresh"))
      sid = AuthService.refreshSid(auth.cookie(req, "REFRESH_COOKIE_NAME", "lab_refresh"));
    else {
      String access = auth.cookie(req, "ACCESS_COOKIE_NAME", "lab_access");
      sid = access == null ? null : auth.decode(access, true);
    }
    if (sid == null || !sid.equals(auth.csrfSid(cookie)))
      throw new ApiError("CSRF_SESSION_MISMATCH", "CSRF 令牌与登录会话不匹配", 403);
  }
}
