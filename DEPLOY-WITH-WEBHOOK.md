
### Chroma 1.0.0 向量库部署

AI 助手的 RAG 检索依赖 Chroma 容器。`docker-compose.yml` 已加入 `chroma` service：

```yaml
chroma:
  image: chromadb/chroma:1.0.0
  container_name: lab-chroma
  restart: unless-stopped
  volumes:
    - chroma_data:/chroma/chroma
  ports:
    - "127.0.0.1:8000:8000"   # localhost-only, prod 用内部网络
  environment:
    - IS_PERSISTENT=TRUE
    - PERSIST_DIRECTORY=/chroma/chroma
    - ANONYMIZED_TELEMETRY=FALSE
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/api/v2/heartbeat"]
    interval: 30s
    timeout: 5s
    retries: 3
```

部署步骤：

```bash
docker compose up -d chroma        # 仅启 chroma（开发期）
sleep 5
curl -s http://localhost:8000/api/v2/heartbeat   # 期望 {"nanosecond heartbeat": N}
```

数据迁移注意：
- Chroma 数据持久化在 `chroma_data` 卷（`/var/lib/docker/volumes/chroma_chroma_data`）；备份/恢复直接挂卷即可。
- 切换 embedding 模型（BGE-M3 → 别的）需要重建 collection——通过 `RagIngestService.rebuildCollection()` 调 `vectorStore.deleteCollection("lab_manuals")`，再重新 ingest。
- 单实例假设：所有 `ai_*` 表 + Chroma + Redis 全在同一台机器；横向扩展场景需考虑 Chroma 的分布式部署或迁到 Pinecone/Weaviate 等托管服务（论文列为未来工作）。
- 启动顺序：MySQL → Redis → Chroma → app；Chroma 健康检查失败不会阻塞 app 启动（Spring AI 是 lazy 初始化），但首次 RAG 调用会 503。

