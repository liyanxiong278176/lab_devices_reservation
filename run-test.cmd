@echo off
set JAVA_HOME=D:\jdk17\jdk-17.0.13+11
set PATH=D:\jdk17\jdk-17.0.13+11\bin;D:\apache-maven-3.9.9\bin;%PATH%
set DOCKER_HOST=http://localhost:2375
set TESTCONTAINERS_RYUK_DISABLED=true
cd /d D:\agent_learning\lab_devices_reservation
mvn test -Dtest=ReservationConcurrencyIT -Ddocker.host=http://localhost:2375 -DforkCount=0 -DargLine="-DDOCKER_HOST=http://localhost:2375" 2>&1
exit /b %ERRORLEVEL%