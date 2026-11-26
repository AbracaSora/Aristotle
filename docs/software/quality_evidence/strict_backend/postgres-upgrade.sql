BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> 0001_learning_workflow

CREATE TABLE graphs (
    sequence SERIAL NOT NULL, 
    version VARCHAR NOT NULL, 
    nodes JSON NOT NULL, 
    PRIMARY KEY (sequence), 
    UNIQUE (version)
);

CREATE TABLE learning_resources (
    id VARCHAR NOT NULL, 
    knowledge_id VARCHAR NOT NULL, 
    title VARCHAR NOT NULL, 
    text TEXT NOT NULL, 
    source VARCHAR NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE learning_scopes (
    id VARCHAR NOT NULL, 
    title VARCHAR NOT NULL, 
    knowledge_ids JSON NOT NULL, 
    published BOOLEAN NOT NULL, 
    description TEXT NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE questions (
    key VARCHAR NOT NULL, 
    question_id VARCHAR NOT NULL, 
    version INTEGER NOT NULL, 
    knowledge_id VARCHAR NOT NULL, 
    prompt TEXT NOT NULL, 
    options JSON NOT NULL, 
    answer VARCHAR NOT NULL, 
    explanation TEXT NOT NULL, 
    source TEXT NOT NULL, 
    status VARCHAR NOT NULL, 
    level VARCHAR, 
    dataset VARCHAR NOT NULL, 
    PRIMARY KEY (key), 
    UNIQUE (question_id, version)
);

CREATE TABLE system_settings (
    key VARCHAR NOT NULL, 
    data JSON NOT NULL, 
    PRIMARY KEY (key)
);

CREATE TABLE users (
    id VARCHAR NOT NULL, 
    username VARCHAR NOT NULL, 
    password_hash VARCHAR NOT NULL, 
    role VARCHAR NOT NULL, 
    PRIMARY KEY (id), 
    UNIQUE (username)
);

CREATE TABLE annotations (
    id VARCHAR NOT NULL, 
    question_key VARCHAR NOT NULL, 
    payload JSON NOT NULL, 
    provider VARCHAR NOT NULL, 
    rule_version VARCHAR NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(question_key) REFERENCES questions (key)
);

CREATE TABLE audit (
    id VARCHAR NOT NULL, 
    actor_id VARCHAR NOT NULL, 
    action VARCHAR NOT NULL, 
    target VARCHAR NOT NULL, 
    at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(actor_id) REFERENCES users (id)
);

CREATE TABLE content_reports (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    question_key VARCHAR NOT NULL, 
    category VARCHAR NOT NULL, 
    message TEXT NOT NULL, 
    status VARCHAR NOT NULL, 
    resolution TEXT NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(question_key) REFERENCES questions (key), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE diagnostic_rounds (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    scope_id VARCHAR NOT NULL, 
    status VARCHAR NOT NULL, 
    blueprint JSON NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(scope_id) REFERENCES learning_scopes (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_diagnostic_rounds_user_id ON diagnostic_rounds (user_id);

CREATE TABLE learner_profiles (
    user_id VARCHAR NOT NULL, 
    scope_id VARCHAR NOT NULL, 
    PRIMARY KEY (user_id), 
    FOREIGN KEY(scope_id) REFERENCES learning_scopes (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE login_sessions (
    token_hash VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    expires_at FLOAT NOT NULL, 
    PRIMARY KEY (token_hash), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE materials (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    title VARCHAR NOT NULL, 
    text TEXT NOT NULL, 
    knowledge_id VARCHAR NOT NULL, 
    confirmed BOOLEAN NOT NULL, 
    deleted BOOLEAN NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_materials_user_id ON materials (user_id);

CREATE TABLE service_jobs (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    kind VARCHAR NOT NULL, 
    status VARCHAR NOT NULL, 
    params JSON NOT NULL, 
    result JSON NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_service_jobs_user_id ON service_jobs (user_id);

CREATE TABLE tasks (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    mode VARCHAR NOT NULL, 
    graph_version VARCHAR NOT NULL, 
    decision JSON NOT NULL, 
    evidence_snapshot JSON NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_tasks_user_id ON tasks (user_id);

CREATE TABLE attempts (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    task_id VARCHAR NOT NULL, 
    question_key VARCHAR NOT NULL, 
    submission_id VARCHAR NOT NULL, 
    selected VARCHAR NOT NULL, 
    correct BOOLEAN NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(question_key) REFERENCES questions (key), 
    FOREIGN KEY(task_id) REFERENCES tasks (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (task_id, question_key), 
    UNIQUE (user_id, submission_id)
);

CREATE INDEX ix_attempts_user_id ON attempts (user_id);

CREATE TABLE reviews (
    id VARCHAR NOT NULL, 
    annotation_id VARCHAR NOT NULL, 
    reviewer_id VARCHAR NOT NULL, 
    decision VARCHAR NOT NULL, 
    reason TEXT NOT NULL, 
    final_level VARCHAR, 
    content_verified BOOLEAN NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(annotation_id) REFERENCES annotations (id), 
    FOREIGN KEY(reviewer_id) REFERENCES users (id), 
    UNIQUE (annotation_id)
);

CREATE TABLE source_chunks (
    id VARCHAR NOT NULL, 
    material_id VARCHAR NOT NULL, 
    text TEXT NOT NULL, 
    knowledge_id VARCHAR NOT NULL, 
    status VARCHAR NOT NULL, 
    location VARCHAR NOT NULL, 
    implementation VARCHAR NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(material_id) REFERENCES materials (id)
);

CREATE INDEX ix_source_chunks_material_id ON source_chunks (material_id);

CREATE TABLE task_progress (
    task_id VARCHAR NOT NULL, 
    scope_id VARCHAR NOT NULL, 
    round_id VARCHAR, 
    status VARCHAR NOT NULL, 
    data JSON NOT NULL, 
    PRIMARY KEY (task_id), 
    FOREIGN KEY(round_id) REFERENCES diagnostic_rounds (id), 
    FOREIGN KEY(scope_id) REFERENCES learning_scopes (id), 
    FOREIGN KEY(task_id) REFERENCES tasks (id)
);

CREATE TABLE task_questions (
    task_id VARCHAR NOT NULL, 
    question_key VARCHAR NOT NULL, 
    position INTEGER NOT NULL, 
    PRIMARY KEY (task_id, question_key), 
    FOREIGN KEY(question_key) REFERENCES questions (key), 
    FOREIGN KEY(task_id) REFERENCES tasks (id)
);

INSERT INTO alembic_version (version_num) VALUES ('0001_learning_workflow') RETURNING alembic_version.version_num;

-- Running upgrade 0001_learning_workflow -> 0002_semantic_learning

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;

CREATE TABLE model_calls (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    purpose VARCHAR NOT NULL, 
    namespace VARCHAR NOT NULL, 
    model VARCHAR NOT NULL, 
    input_hash VARCHAR NOT NULL, 
    status VARCHAR NOT NULL, 
    reserved_requests INTEGER NOT NULL, 
    external_calls INTEGER NOT NULL, 
    usage JSON NOT NULL, 
    error_code VARCHAR NOT NULL, 
    duration_seconds FLOAT NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE INDEX ix_model_calls_created_at ON model_calls (created_at);

CREATE INDEX ix_model_calls_purpose ON model_calls (purpose);

CREATE INDEX ix_model_calls_user_id ON model_calls (user_id);

CREATE TABLE source_embeddings (
    id VARCHAR NOT NULL, 
    source_key VARCHAR NOT NULL, 
    resource_id VARCHAR, 
    material_id VARCHAR, 
    chunk_id VARCHAR, 
    owner_id VARCHAR, 
    namespace VARCHAR NOT NULL, 
    source_hash VARCHAR NOT NULL, 
    dimensions INTEGER NOT NULL, 
    vector VECTOR NOT NULL, 
    created_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    CONSTRAINT embedding_source_owner CHECK ((resource_id IS NOT NULL AND material_id IS NULL AND owner_id IS NULL AND chunk_id IS NULL) OR (resource_id IS NULL AND material_id IS NOT NULL AND owner_id IS NOT NULL)), 
    FOREIGN KEY(chunk_id) REFERENCES source_chunks (id), 
    FOREIGN KEY(material_id) REFERENCES materials (id), 
    FOREIGN KEY(owner_id) REFERENCES users (id), 
    FOREIGN KEY(resource_id) REFERENCES learning_resources (id), 
    UNIQUE (source_key, namespace)
);

CREATE INDEX ix_source_embeddings_material_id ON source_embeddings (material_id);

CREATE INDEX ix_source_embeddings_namespace ON source_embeddings (namespace);

ALTER TABLE materials ADD COLUMN external_processing_allowed BOOLEAN DEFAULT '0' NOT NULL;

UPDATE alembic_version SET version_num='0002_semantic_learning' WHERE alembic_version.version_num = '0001_learning_workflow';

-- Running upgrade 0002_semantic_learning -> 0003_curriculum_tests

ALTER TABLE attempts DROP CONSTRAINT attempts_user_id_submission_id_key;

ALTER TABLE attempts ADD CONSTRAINT uq_attempt_task_submission UNIQUE (user_id, task_id, submission_id);

CREATE TABLE curriculum_subjects (
    id VARCHAR NOT NULL, 
    data JSON NOT NULL, 
    PRIMARY KEY (id)
);

CREATE TABLE curriculum_chapters (
    id VARCHAR NOT NULL, 
    subject_id VARCHAR NOT NULL, 
    data JSON NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(subject_id) REFERENCES curriculum_subjects (id)
);

CREATE TABLE standard_questions (
    key VARCHAR NOT NULL, 
    data JSON NOT NULL, 
    PRIMARY KEY (key), 
    FOREIGN KEY(key) REFERENCES questions (key)
);

CREATE TABLE curriculum_points (
    id VARCHAR NOT NULL, 
    chapter_id VARCHAR NOT NULL, 
    graph_version VARCHAR NOT NULL, 
    data JSON NOT NULL, 
    updated_at FLOAT NOT NULL, 
    PRIMARY KEY (id), 
    FOREIGN KEY(chapter_id) REFERENCES curriculum_chapters (id)
);

CREATE TABLE preset_tasks (
    user_id VARCHAR NOT NULL, 
    preset_set_id VARCHAR NOT NULL, 
    preset_set_version INTEGER NOT NULL, 
    task_id VARCHAR NOT NULL, 
    PRIMARY KEY (user_id, preset_set_id, preset_set_version), 
    FOREIGN KEY(task_id) REFERENCES tasks (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (task_id)
);

CREATE TABLE final_tests (
    id VARCHAR NOT NULL, 
    user_id VARCHAR NOT NULL, 
    knowledge_id VARCHAR NOT NULL, 
    version INTEGER NOT NULL, 
    request_id VARCHAR NOT NULL, 
    preset_set_id VARCHAR NOT NULL, 
    preset_set_version INTEGER NOT NULL, 
    status VARCHAR NOT NULL, 
    rules JSON NOT NULL, 
    generation_context JSON NOT NULL, 
    questions JSON NOT NULL, 
    result JSON, 
    error JSON, 
    submission_id VARCHAR, 
    submission_hash VARCHAR, 
    client_context JSON NOT NULL, 
    created_at FLOAT NOT NULL, 
    started_at FLOAT, 
    submitted_at FLOAT, 
    PRIMARY KEY (id), 
    CONSTRAINT test_status CHECK (status IN ('generating','ready','generation_failed','submitted')), 
    CONSTRAINT positive_test_version CHECK (version > 0), 
    FOREIGN KEY(knowledge_id) REFERENCES curriculum_points (id), 
    FOREIGN KEY(user_id) REFERENCES users (id), 
    UNIQUE (user_id, knowledge_id, version), 
    UNIQUE (user_id, request_id)
);

CREATE INDEX ix_final_tests_user_id ON final_tests (user_id);

CREATE UNIQUE INDEX uq_final_test_active ON final_tests (user_id, knowledge_id) WHERE status IN ('generating', 'ready');

CREATE TABLE preset_sets (
    id VARCHAR NOT NULL, 
    version INTEGER NOT NULL, 
    knowledge_id VARCHAR NOT NULL, 
    question_keys JSON NOT NULL, 
    PRIMARY KEY (id, version), 
    FOREIGN KEY(knowledge_id) REFERENCES curriculum_points (id)
);

UPDATE alembic_version SET version_num='0003_curriculum_tests' WHERE alembic_version.version_num = '0002_semantic_learning';

COMMIT;

