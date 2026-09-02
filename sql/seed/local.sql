-- Deterministic local identities; no provider credentials are stored here.
INSERT INTO tenant (id, slug, name, tier, status)
VALUES (
    '00000000-0000-0000-0000-000000000002',
    'baptist-local',
    'Baptist Local Workspace',
    'baptist',
    'active'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO user_profile (id, email, full_name)
VALUES
    ('00000000-0000-0000-0000-000000000001', 'admin@local.baptist.test', 'Local Admin'),
    ('00000000-0000-0000-0000-000000000003', 'viewer@local.baptist.test', 'Local Viewer')
ON CONFLICT (id) DO NOTHING;

INSERT INTO membership (tenant_id, user_id, role, status, joined_at)
VALUES
    ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', 'as_admin', 'active', now()),
    ('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000003', 'client_user', 'active', now())
ON CONFLICT (tenant_id, user_id) DO NOTHING;
