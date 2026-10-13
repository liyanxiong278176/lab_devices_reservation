package edu.labflow;

import io.micrometer.core.instrument.*;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

@Component
public class RuntimeMetrics {
  public RuntimeMetrics(ObjectProvider<MeterRegistry> registries, OutboxWorker worker) {
    registries.ifAvailable(
        registry -> {
          Gauge.builder("outbox_worker_active_tasks", worker, OutboxWorker::activeTasks)
              .register(registry);
          FunctionCounter.builder("outbox_claimed", worker, OutboxWorker::claimedTasks)
              .register(registry);
          FunctionCounter.builder("outbox_failed", worker, OutboxWorker::failedTasks)
              .register(registry);
        });
  }
}
