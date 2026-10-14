package edu.labflow;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class LabFlowApplication {
  public static void main(String[] args) {
    var app = new SpringApplication(LabFlowApplication.class);
    app.addInitializers(new RuntimeEnvironment());
    var context = app.run(args);
    if (!context.getEnvironment().getProperty("labflow.migration", "none").equals("none")
        || !context.getEnvironment().getProperty("labflow.fixture", "none").equals("none"))
      context.close();
  }
}
