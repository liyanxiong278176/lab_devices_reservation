package edu.labflow;

import java.io.IOException;
import java.nio.file.*;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * Completes destructive file cleanup after the database migration, retrying on the next startup.
 */
@Component
public class RemovedWorkflowFiles implements ApplicationRunner {
  private final Database db;
  private final Settings settings;

  public RemovedWorkflowFiles(Database db, Settings settings) {
    this.db = db;
    this.settings = settings;
  }

  @Override
  public void run(ApplicationArguments args) throws IOException {
    if (db.count(
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='v2_removed_workflow_file_cleanup'")
        == 0) return;
    for (var row :
        db.rows("SELECT id,storage_path FROM v2_removed_workflow_file_cleanup ORDER BY id")) {
      Path root = settings.uploads().toAbsolutePath().normalize();
      Path stored = Path.of(row.get("storage_path").toString());
      Path file = (stored.isAbsolute() ? stored : root.resolve(stored.getFileName())).normalize();
      if (!file.startsWith(root)) file = root.resolve(stored.getFileName());
      if (Files.exists(file, LinkOption.NOFOLLOW_LINKS)) {
        Path realRoot = root.toRealPath();
        if (!file.toRealPath().startsWith(realRoot) || Files.isSymbolicLink(file))
          throw new IOException("Workflow attachment outside upload root");
        Files.delete(file);
      }
      db.execute("DELETE FROM v2_removed_workflow_file_cleanup WHERE id=?", row.get("id"));
    }
  }
}
