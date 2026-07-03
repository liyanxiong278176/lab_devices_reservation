# stage1: build
FROM maven:3.9-eclipse-temurin-17 AS builder
WORKDIR /build
# 中国网络：容器内直连 Maven Central 会超时，先注入阿里云镜像 settings
COPY .mvn/docker-settings.xml /root/.m2/settings.xml
# 先 copy pom 跑依赖解析（利用 Docker 层缓存）
COPY pom.xml .
RUN mvn -B dependency:go-offline
COPY src ./src
RUN mvn -B package -DskipTests

# stage2: runtime
FROM eclipse-temurin:17-jre-jammy
WORKDIR /app
COPY --from=builder /build/target/*.jar app.jar
EXPOSE 8080
ENTRYPOINT ["java","-jar","/app/app.jar","--spring.profiles.active=prod"]
