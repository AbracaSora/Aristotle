BEGIN;

-- Running downgrade 0003_curriculum_tests -> 0002_semantic_learning

ALTER TABLE attempts DROP CONSTRAINT uq_attempt_task_submission;

ALTER TABLE attempts ADD CONSTRAINT attempts_user_id_submission_id_key UNIQUE (user_id, submission_id);

DROP TABLE preset_sets;

DROP INDEX uq_final_test_active;

DROP INDEX ix_final_tests_user_id;

DROP TABLE final_tests;

DROP TABLE preset_tasks;

DROP TABLE curriculum_points;

DROP TABLE standard_questions;

DROP TABLE curriculum_chapters;

DROP TABLE curriculum_subjects;

UPDATE alembic_version SET version_num='0002_semantic_learning' WHERE alembic_version.version_num = '0003_curriculum_tests';

-- Running downgrade 0002_semantic_learning -> 0001_learning_workflow

ALTER TABLE materials DROP COLUMN external_processing_allowed;

DROP INDEX ix_source_embeddings_namespace;

DROP INDEX ix_source_embeddings_material_id;

DROP TABLE source_embeddings;

DROP INDEX ix_model_calls_user_id;

DROP INDEX ix_model_calls_purpose;

DROP INDEX ix_model_calls_created_at;

DROP TABLE model_calls;

UPDATE alembic_version SET version_num='0001_learning_workflow' WHERE alembic_version.version_num = '0002_semantic_learning';

-- Running downgrade 0001_learning_workflow -> 

DROP TABLE task_questions;

DROP TABLE task_progress;

DROP INDEX ix_source_chunks_material_id;

DROP TABLE source_chunks;

DROP TABLE reviews;

DROP INDEX ix_attempts_user_id;

DROP TABLE attempts;

DROP INDEX ix_tasks_user_id;

DROP TABLE tasks;

DROP INDEX ix_service_jobs_user_id;

DROP TABLE service_jobs;

DROP INDEX ix_materials_user_id;

DROP TABLE materials;

DROP TABLE login_sessions;

DROP TABLE learner_profiles;

DROP INDEX ix_diagnostic_rounds_user_id;

DROP TABLE diagnostic_rounds;

DROP TABLE content_reports;

DROP TABLE audit;

DROP TABLE annotations;

DROP TABLE users;

DROP TABLE system_settings;

DROP TABLE questions;

DROP TABLE learning_scopes;

DROP TABLE learning_resources;

DROP TABLE graphs;

DELETE FROM alembic_version WHERE alembic_version.version_num = '0001_learning_workflow';

DROP TABLE alembic_version;

COMMIT;

