FROM maven:3.9.11-eclipse-temurin-21 AS build
WORKDIR /build
COPY backend-java/pom.xml ./
RUN mvn -B dependency:go-offline
COPY backend-java/src ./src
RUN mvn -B package -DskipTests
FROM eclipse-temurin:21-jre-jammy
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 labflow && mkdir -p /app/backend/.data/uploads \
    && chown -R labflow /app
WORKDIR /app
COPY --from=build /build/target/labflow-backend-1.0.0.jar /app/backend-java/app.jar
USER labflow
ENV LAB_ENVIRONMENT=prod
ENV LAB_ENABLE_WORKERS=true
ENV JAVA_TOOL_OPTIONS="-XX:MaxRAMPercentage=65 -XX:+ExitOnOutOfMemoryError"
EXPOSE 8000
CMD ["java", "-jar", "/app/backend-java/app.jar"]
