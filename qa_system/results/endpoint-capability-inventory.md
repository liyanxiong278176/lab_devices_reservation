# Endpoint and capability inventory

Routes: **142**. Source: FastAPI OpenAPI plus dependency inspection.
Tenant scope is source evidence; API tests check cross-tenant behavior.
Settings list names and types only; credential values are never serialized.

## REST endpoints

| Method | Path | Tag | Request schema | Auth | Tenant scope evidence | CSRF |
|---|---|---|---|---|---|---|
| GET | `/api/v2/ai/citations/business/{citation_id}` | ai | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/ai/citations/knowledge/{point_id}` | ai | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/ai/config` | ai | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/ai/config/components` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/config/{component}/test` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/ai/confirmations/{confirmation_id}/cancel` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/ai/confirmations/{confirmation_id}/confirm` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/conversations` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/conversations` | ai | `ConversationCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/ai/conversations/{conversation_id}` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/conversations/{conversation_id}/active-run` | ai | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/ai/conversations/{conversation_id}/messages` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/conversations/{conversation_id}/stream` | ai | `ChatRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/domain-terms` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/domain-terms` | ai | `AiDomainTermCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/ai/domain-terms/{term_id}` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/ai/embedding/rebuild` | ai | `AiEmbeddingRebuildRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/embedding/rebuild/latest` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/embedding/rebuild/{job_id}/rollback` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/knowledge` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/knowledge` | ai | `KnowledgeCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/knowledge/scope-roles` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/knowledge/upload` | ai | `Body_upload_knowledge_document_api_v2_ai_knowledge_upload_post` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/ai/knowledge/{document_id}` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/knowledge/{document_id}` | ai | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}/retry` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/ai/knowledge/{document_id}/build-jobs/{job_id}/skip` | ai | `KnowledgeBuildSkipRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/knowledge/{document_id}/chunks/preview` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/knowledge/{document_id}/parse` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/ai/knowledge/{document_id}/publish` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| PUT | `/api/v2/ai/knowledge/{document_id}/review` | ai | `KnowledgeReviewRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/ai/memories/{memory_id}/confirm` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/ai/memories/{memory_id}/reject` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/runs/{run_id}/events` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/ai/runs/{run_id}/stop` | ai | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ai/status` | ai | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/ai/usage` | ai | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/approvals/batch-approve` | reservations | `BatchApprovalRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/approvals/pending` | reservations | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/approvals/{reservation_id}/approve` | reservations | `{"anyOf": [{"$ref": "#/components/schemas/ApprovalRequest"}, {"type": "null"}], "title": "Payload"}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/approvals/{reservation_id}/reject` | reservations | `ApprovalRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/auth/colleges` | auth | `{}` | public/session bootstrap | review service/query path | not required by method |
| GET | `/api/v2/auth/csrf` | auth | `{}` | public/session bootstrap | review service/query path | not required by method |
| POST | `/api/v2/auth/login` | auth | `LoginRequest` | public/session bootstrap | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/auth/logout` | auth | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/auth/me` | auth | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/auth/refresh` | auth | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/auth/register` | auth | `RegisterRequest` | public/session bootstrap | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/blackouts` | scheduling | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/blackouts` | scheduling | `BlackoutCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/blackouts/{blackout_id}` | scheduling | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/colleges` | catalog | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/colleges` | catalog | `CollegeWriteRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| PUT | `/api/v2/colleges/{college_id}` | catalog | `CollegeWriteRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/dashboard/me` | dashboard | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/dashboard/overview` | dashboard | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/dashboard/summary` | dashboard | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/device-categories` | catalog | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/devices` | devices | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/devices` | devices | `DeviceCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/devices/{device_id}` | devices | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/devices/{device_id}` | devices | `{}` | cookie session required | review service/query path | not required by method |
| PUT | `/api/v2/devices/{device_id}` | devices | `DeviceUpdateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/devices/{device_id}/access` | device-access | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/devices/{device_id}/availability` | devices | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/devices/{device_id}/documents` | device-documents | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/devices/{device_id}/documents` | device-documents | `Body_upload_device_document_api_v2_devices__device_id__documents_post` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/devices/{device_id}/documents/{document_id}` | device-documents | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/devices/{device_id}/maintenance-evidence` | maintenance | `Body_upload_maintenance_evidence_api_v2_devices__device_id__maintenance_evidence_post` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/devices/{device_id}/maintenance-plans` | maintenance | `MaintenancePlanWrite` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/devices/{device_id}/qualification-uploads` | device-access | `Body_upload_qualification_material_api_v2_devices__device_id__qualification_uploads_post` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/devices/{device_id}/qualifications` | device-access | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/devices/{device_id}/qualifications` | device-access | `QualificationSubmitRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/devices/{device_id}/qualifications/mine` | device-access | `{}` | cookie session required | review service/query path | not required by method |
| PATCH | `/api/v2/devices/{device_id}/qualifications/{qualification_id}` | device-access | `QualificationReviewRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/devices/{device_id}/safety-ack` | device-access | `SafetyAcknowledgementRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/devices/{device_id}/safety-documents` | device-access | `{}` | cookie session required | review service/query path | not required by method |
| PATCH | `/api/v2/devices/{device_id}/status` | devices | `DeviceStatusRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/labs` | catalog | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/labs` | catalog | `LabWriteRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| PUT | `/api/v2/labs/{lab_id}` | catalog | `LabWriteRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/live` | system | `{}` | public/session bootstrap | review service/query path | not required by method |
| GET | `/api/v2/maintenance-devices` | maintenance | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/maintenance-plans` | maintenance | `{}` | cookie session required | review service/query path | not required by method |
| PUT | `/api/v2/maintenance-plans/{plan_id}` | maintenance | `MaintenancePlanWrite` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/maintenance-plans/{plan_id}/records` | maintenance | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/maintenance-plans/{plan_id}/records` | maintenance | `MaintenanceRecordCreate` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/notifications/mine` | notifications | `{}` | cookie session required | review service/query path | not required by method |
| PATCH | `/api/v2/notifications/read-all` | notifications | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/notifications/stream` | notifications | `{}` | cookie session required | review service/query path | not required by method |
| PATCH | `/api/v2/notifications/{notification_id}/read` | notifications | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/organization/managers` | catalog | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/rbac/permissions` | rbac | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/rbac/roles` | rbac | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/rbac/roles` | rbac | `RoleCreate` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/rbac/roles/{role_id}` | rbac | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| PATCH | `/api/v2/rbac/roles/{role_id}` | rbac | `RoleRename` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| PUT | `/api/v2/rbac/roles/{role_id}/permissions` | rbac | `RolePermissionUpdate` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/ready` | system | `{}` | public/session bootstrap | review service/query path | not required by method |
| GET | `/api/v2/recommendations` | recommendations | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/repair-reports` | repairs | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/repair-reports` | repairs | `RepairCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/repair-reports/mine` | repairs | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/repair-reports/{report_id}/confirm` | repairs | `RepairConfirmRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/repair-reports/{report_id}/reject` | repairs | `RepairHandleRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/repair-reports/{report_id}/resolve` | repairs | `RepairHandleRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/repair-reports/{report_id}/take` | repairs | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/repair-reports/{report_id}/worklogs` | repairs | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/repair-uploads` | repairs | `Body_upload_repair_image_api_v2_repair_uploads_post` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/reports/export/{export_type}` | reports | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/reports/exports` | reports | `ExportCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/reports/exports/{task_id}` | reports | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/reports/summary` | reports | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/reservation-rules` | reservation-rules | `{}` | cookie session required | review service/query path | not required by method |
| PUT | `/api/v2/reservation-rules` | reservation-rules | `ReservationRuleWrite` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/reservation-rules/{rule_id}` | reservation-rules | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations` | reservations | `ReservationPlanRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/reservations/handovers` | reservations | `{}` | cookie session required | review service/query path | not required by method |
| GET | `/api/v2/reservations/mine` | reservations | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/reservations/preflight` | reservations | `ReservationPlanRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/waitlist` | reservations | `WaitlistCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/reservations/waitlist/mine` | reservations | `{}` | cookie session required | review service/query path | not required by method |
| DELETE | `/api/v2/reservations/waitlist/{entry_id}` | reservations | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/waitlist/{entry_id}/confirm` | reservations | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/reservations/{reservation_id}` | reservations | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/reservations/{reservation_id}/accept-return` | reservations | `ReturnAcceptanceRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/{reservation_id}/cancel` | reservations | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/{reservation_id}/cancel-handover-exception` | reservations | `ApprovalRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/{reservation_id}/check-in` | reservations | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/reservations/{reservation_id}/feedback` | feedback | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/reservations/{reservation_id}/feedback` | feedback | `FeedbackCreateRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/{reservation_id}/handover` | reservations | `HandoverRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/{reservation_id}/return` | reservations | `ReturnInspectionRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| POST | `/api/v2/reservations/{reservation_id}/violate` | reservations | `ApprovalRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/system/outbox/failed` | system | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/system/outbox/{task_id}/retry` | system | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| GET | `/api/v2/users` | users | `{}` | cookie session required | review service/query path | not required by method |
| POST | `/api/v2/users` | users | `UserRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| DELETE | `/api/v2/users/{user_id}` | users | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| PUT | `/api/v2/users/{user_id}` | users | `UserRequest` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |
| PATCH | `/api/v2/users/{user_id}/status` | users | `{}` | cookie session required | review service/query path | trusted Origin + double-submit CSRF |

## AI tools and policy

| Tool | Permission | Write | Confirmation | Policy |
|---|---|---:|---|---|
| `cancel_reservation` | `reservation:cancel` | true | required | 取消当前用户自己的预约；必须经过用户确认 |
| `check_availability` | `device:read` | false | not required | 查询当前学院设备在自然日期上的可用性 |
| `create_reservation` | `reservation:create` | true | required | 创建预约；只能先生成预览，必须经过用户确认 |
| `my_reservations` | `reservation:read:own` | false | not required | 查询当前用户自己的预约 |
| `recommend_devices` | `device:read` | false | not required | 基于当前学院可见设备、用户偏好和近期热度生成可解释推荐 |
| `search_devices` | `device:read` | false | not required | 查询当前用户所属学院可见的设备 |
| `submit_repair` | `repair:create` | true | required | 提交设备报修；必须经过用户确认 |

## Settings surface

| Setting | Type | Value handling |
|---|---|---|
| `access_cookie_name` | `<class 'str'>` | value omitted |
| `access_token_minutes` | `<class 'int'>` | never exported |
| `ai_allowed_base_urls` | `list[str]` | value omitted |
| `ai_allowed_models` | `list[str]` | value omitted |
| `ai_api_key` | `str | None` | never exported |
| `ai_base_url` | `<class 'str'>` | value omitted |
| `ai_college_daily_token_cap` | `<class 'int'>` | never exported |
| `ai_confirmation_ttl_minutes` | `<class 'int'>` | value omitted |
| `ai_daily_reservation_tokens` | `<class 'int'>` | never exported |
| `ai_embedding_api_key` | `str | None` | never exported |
| `ai_embedding_base_url` | `<class 'str'>` | value omitted |
| `ai_embedding_dimension` | `<class 'int'>` | value omitted |
| `ai_embedding_model` | `<class 'str'>` | value omitted |
| `ai_embedding_provider` | `<class 'str'>` | value omitted |
| `ai_global_daily_token_cap` | `<class 'int'>` | never exported |
| `ai_knowledge_build_dispatch_recovery_seconds` | `<class 'int'>` | value omitted |
| `ai_knowledge_build_embed_batch_size` | `<class 'int'>` | value omitted |
| `ai_knowledge_build_lease_seconds` | `<class 'int'>` | value omitted |
| `ai_knowledge_build_max_redeliveries` | `<class 'int'>` | value omitted |
| `ai_knowledge_build_reconcile_interval_seconds` | `<class 'int'>` | value omitted |
| `ai_knowledge_college_storage_bytes` | `<class 'int'>` | value omitted |
| `ai_knowledge_global_storage_bytes` | `<class 'int'>` | value omitted |
| `ai_max_context_documents` | `<class 'int'>` | value omitted |
| `ai_max_input_chars` | `<class 'int'>` | value omitted |
| `ai_max_output_tokens` | `<class 'int'>` | never exported |
| `ai_message_retention_days` | `<class 'int'>` | value omitted |
| `ai_mineru_api_key` | `str | None` | never exported |
| `ai_mineru_base_url` | `<class 'str'>` | value omitted |
| `ai_mineru_model` | `<class 'str'>` | value omitted |
| `ai_model` | `<class 'str'>` | value omitted |
| `ai_provider` | `<class 'str'>` | value omitted |
| `ai_provider_timeout_seconds` | `<class 'float'>` | value omitted |
| `ai_qdrant_collection` | `<class 'str'>` | value omitted |
| `ai_qdrant_timeout_seconds` | `<class 'int'>` | value omitted |
| `ai_rag_query_concurrency` | `<class 'int'>` | value omitted |
| `ai_reranker_model` | `<class 'str'>` | value omitted |
| `ai_run_event_heartbeat_seconds` | `<class 'float'>` | value omitted |
| `ai_run_event_poll_seconds` | `<class 'float'>` | value omitted |
| `ai_upload_max_bytes` | `<class 'int'>` | value omitted |
| `ai_user_daily_token_cap` | `<class 'int'>` | never exported |
| `api_prefix` | `<class 'str'>` | value omitted |
| `api_version` | `<class 'str'>` | value omitted |
| `app_name` | `<class 'str'>` | value omitted |
| `bootstrap_admin_password` | `str | None` | never exported |
| `bootstrap_admin_username` | `<class 'str'>` | value omitted |
| `cache_default_ttl_seconds` | `<class 'int'>` | value omitted |
| `cache_hot_key_lock_seconds` | `<class 'int'>` | value omitted |
| `cache_hot_key_wait_seconds` | `<class 'float'>` | value omitted |
| `cache_negative_ttl_seconds` | `<class 'int'>` | value omitted |
| `cache_ttl_jitter_seconds` | `<class 'int'>` | value omitted |
| `celery_broker_url` | `<class 'str'>` | value omitted |
| `celery_task_soft_time_limit_seconds` | `<class 'int'>` | value omitted |
| `celery_task_time_limit_seconds` | `<class 'int'>` | value omitted |
| `celery_visibility_timeout_seconds` | `<class 'int'>` | value omitted |
| `celery_worker_concurrency` | `<class 'int'>` | value omitted |
| `cookie_domain` | `str | None` | value omitted |
| `cookie_secure` | `<class 'bool'>` | value omitted |
| `cors_origins` | `list[str]` | value omitted |
| `credit_block_days` | `<class 'int'>` | value omitted |
| `credit_block_threshold` | `<class 'int'>` | value omitted |
| `csrf_cookie_name` | `<class 'str'>` | value omitted |
| `db_max_overflow` | `<class 'int'>` | value omitted |
| `db_pool_recycle_seconds` | `<class 'int'>` | value omitted |
| `db_pool_size` | `<class 'int'>` | value omitted |
| `db_pool_timeout_seconds` | `<class 'int'>` | value omitted |
| `debug` | `<class 'bool'>` | value omitted |
| `enable_workers` | `<class 'bool'>` | value omitted |
| `environment` | `typing.Literal['local', 'test', 'dev', 'prod']` | value omitted |
| `export_sync_row_limit` | `<class 'int'>` | value omitted |
| `jwt_audience` | `<class 'str'>` | value omitted |
| `jwt_issuer` | `<class 'str'>` | value omitted |
| `jwt_secret` | `<class 'str'>` | never exported |
| `metrics_token` | `str | None` | never exported |
| `mysql_dsn` | `<class 'str'>` | never exported |
| `notification_sse_auth_timeout_seconds` | `<class 'float'>` | value omitted |
| `notification_sse_heartbeat_seconds` | `<class 'float'>` | value omitted |
| `notification_sse_max_connections` | `<class 'int'>` | value omitted |
| `notification_sse_max_pending` | `<class 'int'>` | value omitted |
| `notification_sse_max_pending_per_ip` | `<class 'int'>` | value omitted |
| `notification_sse_max_per_user` | `<class 'int'>` | value omitted |
| `notification_sse_max_replay_events` | `<class 'int'>` | value omitted |
| `notification_sse_revalidate_seconds` | `<class 'float'>` | value omitted |
| `outbox_claim_timeout_seconds` | `<class 'int'>` | value omitted |
| `outbox_max_attempts` | `<class 'int'>` | value omitted |
| `outbox_retry_base_seconds` | `<class 'int'>` | value omitted |
| `outbox_task_timeout_seconds` | `<class 'float'>` | value omitted |
| `outbox_worker_concurrency` | `<class 'int'>` | value omitted |
| `qdrant_url` | `<class 'str'>` | value omitted |
| `rate_limit_default_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_default_refill_per_second` | `<class 'float'>` | value omitted |
| `rate_limit_enabled` | `<class 'bool'>` | value omitted |
| `rate_limit_local_max_entries` | `<class 'int'>` | value omitted |
| `rate_limit_login_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_login_ip_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_login_ip_refill_per_second` | `<class 'float'>` | value omitted |
| `rate_limit_login_refill_per_second` | `<class 'float'>` | value omitted |
| `rate_limit_redis_timeout_seconds` | `<class 'float'>` | value omitted |
| `rate_limit_register_ip_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_register_ip_refill_per_second` | `<class 'float'>` | value omitted |
| `rate_limit_register_username_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_register_username_refill_per_second` | `<class 'float'>` | value omitted |
| `rate_limit_repair_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_repair_refill_per_second` | `<class 'float'>` | value omitted |
| `rate_limit_reservation_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_reservation_refill_per_second` | `<class 'float'>` | value omitted |
| `rate_limit_upload_capacity` | `<class 'int'>` | value omitted |
| `rate_limit_upload_refill_per_second` | `<class 'float'>` | value omitted |
| `recommend_cache_ttl_seconds` | `<class 'int'>` | value omitted |
| `redis_circuit_failure_threshold` | `<class 'int'>` | value omitted |
| `redis_circuit_recovery_seconds` | `<class 'float'>` | value omitted |
| `redis_socket_timeout_seconds` | `<class 'float'>` | value omitted |
| `redis_url` | `<class 'str'>` | value omitted |
| `refresh_cookie_name` | `<class 'str'>` | value omitted |
| `refresh_token_days` | `<class 'int'>` | never exported |
| `repair_sla_days` | `dict[str, int]` | value omitted |
| `repair_user_confirmation_days` | `<class 'int'>` | value omitted |
| `request_health_capacity` | `<class 'int'>` | value omitted |
| `request_queue_capacity` | `<class 'int'>` | value omitted |
| `reservation_advance_days` | `<class 'int'>` | value omitted |
| `reservation_lock_poll_seconds` | `<class 'float'>` | value omitted |
| `reservation_lock_ttl_seconds` | `<class 'int'>` | value omitted |
| `reservation_lock_wait_seconds` | `<class 'float'>` | value omitted |
| `reservation_manager_advance_days` | `<class 'int'>` | value omitted |
| `reservation_max_days` | `<class 'int'>` | value omitted |
| `trusted_proxy_ips` | `list[str]` | value omitted |
| `upload_cleanup_interval_seconds` | `<class 'int'>` | value omitted |
| `upload_college_quota_bytes` | `<class 'int'>` | value omitted |
| `upload_dir` | `<class 'str'>` | value omitted |
| `upload_max_bytes` | `<class 'int'>` | value omitted |
| `upload_orphan_retention_hours` | `<class 'int'>` | value omitted |
| `upload_total_quota_bytes` | `<class 'int'>` | value omitted |
| `upload_user_quota_bytes` | `<class 'int'>` | value omitted |
