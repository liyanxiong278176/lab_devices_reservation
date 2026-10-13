package edu.labflow;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

@Component
public class BootstrapAdmin implements ApplicationRunner {
  private final Database db;
  private final AuthService auth;
  private final Settings settings;

  public BootstrapAdmin(Database db, AuthService auth, Settings settings) {
    this.db = db;
    this.auth = auth;
    this.settings = settings;
  }

  @Override
  @Transactional
  public void run(ApplicationArguments args) {
    if (args.containsOption("labflow.migration")) return;
    String password = settings.get("BOOTSTRAP_ADMIN_PASSWORD", "");
    if (password.isBlank()) return;
    if (password.length() < 12)
      throw new IllegalStateException("Bootstrap password must contain at least 12 characters");
    String username = settings.get("BOOTSTRAP_ADMIN_USERNAME", "admin");
    db.one("SELECT version FROM v2_authz_version WHERE id=1 FOR UPDATE");
    if (db.count("SELECT COUNT(*) FROM sys_user WHERE username=?", username) > 0) return;
    long user =
        db.insert(
            "INSERT INTO sys_user (username,password,real_name,user_type,college_id,status,credit_score) VALUES (?,?,?,'STAFF',NULL,1,100)",
            username,
            auth.hash(password),
            "系统管理员");
    if (db.execute(
            "INSERT INTO sys_user_role (user_id,role_id) SELECT ?,id FROM sys_role WHERE role_code='SYS_ADMIN'",
            user)
        != 1)
      throw new IllegalStateException("Apply schema migrations before bootstrapping accounts");
    db.execute("UPDATE v2_authz_version SET version=version+1 WHERE id=1");
  }
}
