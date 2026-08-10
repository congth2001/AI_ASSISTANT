CREATE TEMP TABLE customers (
    customer_id UUID PRIMARY KEY,
    customer_identity_key TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    address_detail TEXT,
    village_name TEXT,
    ward_name TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
) ON COMMIT PRESERVE ROWS;

CREATE TEMP TABLE sales_invoices (
    invoice_id TEXT PRIMARY KEY,
    invoice_number TEXT NOT NULL UNIQUE,
    issued_at TIMESTAMP NOT NULL,
    customer_id UUID NOT NULL REFERENCES customers(customer_id),
    customer_name_snapshot TEXT NOT NULL,
    customer_address_detail_snapshot TEXT,
    customer_village_name_snapshot TEXT,
    customer_ward_name_snapshot TEXT,
    invoice_total_amount NUMERIC(18, 2) NOT NULL,
    debt_delta_amount NUMERIC(18, 2),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP
) ON COMMIT PRESERVE ROWS;

CREATE TEMP TABLE sales_invoice_lines (
    invoice_line_id TEXT PRIMARY KEY,
    invoice_id TEXT NOT NULL REFERENCES sales_invoices(invoice_id),
    line_number INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    product_category_name TEXT,
    unit_name TEXT NOT NULL,
    unit_price NUMERIC(18, 2) NOT NULL,
    quantity NUMERIC(18, 3) NOT NULL,
    line_amount NUMERIC(18, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP,
    UNIQUE (invoice_id, line_number)
) ON COMMIT PRESERVE ROWS;

INSERT INTO customers (
    customer_id, customer_identity_key, customer_name, ward_name, deleted_at
) VALUES
    ('00000000-0000-0000-0000-000000000001', 'an-phat', 'Công ty An Phát', 'Phường 1', NULL),
    ('00000000-0000-0000-0000-000000000002', 'binh-minh', 'Cửa hàng Bình Minh', 'Phường 2', NULL),
    ('00000000-0000-0000-0000-000000000003', 'chi-lan', 'Chị Lan', 'Phường 3', NULL),
    ('00000000-0000-0000-0000-000000000004', 'dai-nam', 'Công ty Đại Nam', 'Phường 4', NULL),
    ('00000000-0000-0000-0000-000000000005', 'deleted-customer', 'Khách đã xóa', 'Phường 5', TIMESTAMPTZ '2025-01-01 00:00:00+07');

INSERT INTO sales_invoices (
    invoice_id,
    invoice_number,
    issued_at,
    customer_id,
    customer_name_snapshot,
    invoice_total_amount,
    debt_delta_amount,
    deleted_at
) VALUES
    ('I001', 'HD-2025-001', TIMESTAMP '2025-01-05 09:00:00', '00000000-0000-0000-0000-000000000001', 'Công ty An Phát', 1000.00, 400.00, NULL),
    ('I002', 'HD-2025-002', TIMESTAMP '2025-01-31 23:59:59', '00000000-0000-0000-0000-000000000002', 'Cửa hàng Bình Minh', 2000.00, 2000.00, NULL),
    ('I003', 'HD-2025-003', TIMESTAMP '2025-02-01 00:00:00', '00000000-0000-0000-0000-000000000001', 'Công ty An Phát', 1500.00, -200.00, NULL),
    ('I004', 'HD-2025-004', TIMESTAMP '2025-02-28 23:59:59', '00000000-0000-0000-0000-000000000003', 'Chị Lan', 3000.00, 1000.00, NULL),
    ('I005', 'HD-2025-005', TIMESTAMP '2025-03-01 00:00:00', '00000000-0000-0000-0000-000000000002', 'Cửa hàng Bình Minh', 2500.00, 500.00, NULL),
    ('I006', 'HD-2025-006', TIMESTAMP '2025-03-15 12:00:00', '00000000-0000-0000-0000-000000000001', 'Công ty An Phát', 4000.00, 3500.00, NULL),
    ('I007', 'HD-2025-007', TIMESTAMP '2025-03-31 23:59:59', '00000000-0000-0000-0000-000000000003', 'Chị Lan', 500.00, NULL, NULL),
    ('I008', 'HD-2025-008', TIMESTAMP '2025-04-01 00:00:00', '00000000-0000-0000-0000-000000000001', 'Công ty An Phát', 9000.00, 9000.00, NULL),
    ('I009', 'HD-2025-009', TIMESTAMP '2025-03-20 10:00:00', '00000000-0000-0000-0000-000000000002', 'Cửa hàng Bình Minh', 9999.00, 9999.00, TIMESTAMP '2025-03-21 08:00:00'),
    ('I010', 'HD-2025-010', TIMESTAMP '2025-02-10 10:00:00', '00000000-0000-0000-0000-000000000002', 'Cửa hàng Bình Minh', 700.00, 0.00, NULL);

INSERT INTO sales_invoice_lines (
    invoice_line_id,
    invoice_id,
    line_number,
    product_name,
    product_category_name,
    unit_name,
    unit_price,
    quantity,
    line_amount,
    deleted_at
) VALUES
    ('L001', 'I001', 1, 'Xi măng PCB40', 'Xi măng', 'bao', 60.00, 10.000, 600.00, NULL),
    ('L002', 'I001', 2, 'Cát xây dựng', 'Cát', 'm3', 50.00, 7.000, 350.00, NULL),
    ('L003', 'I002', 1, 'Gạch A', 'Gạch', 'viên', 12.00, 100.000, 1200.00, NULL),
    ('L004', 'I002', 2, 'Xi măng PCB40', 'Xi măng', 'bao', 80.00, 10.000, 800.00, NULL),
    ('L005', 'I003', 1, 'Gạch A', 'Gạch', 'viên', 12.50, 80.000, 1000.00, NULL),
    ('L006', 'I003', 2, 'Cát xây dựng', 'Cát', 'm3', 50.00, 9.000, 450.00, NULL),
    ('L007', 'I004', 1, 'Thép D10', 'Sắt', 'cây', 60.00, 30.000, 1800.00, NULL),
    ('L008', 'I004', 2, 'Gạch B', 'Gạch', 'viên', 20.00, 55.000, 1100.00, NULL),
    ('L009', 'I005', 1, 'Xi măng PCB40', 'Xi măng', 'bao', 80.00, 12.500, 1000.00, NULL),
    ('L010', 'I005', 2, 'Gạch A', 'Gạch', 'viên', 11.6667, 120.000, 1400.00, NULL),
    ('L011', 'I006', 1, 'Thép D10', 'Sắt', 'cây', 62.50, 40.000, 2500.00, NULL),
    ('L012', 'I006', 2, 'Gạch B', 'Gạch', 'viên', 20.00, 70.000, 1400.00, NULL),
    ('L013', 'I007', 1, 'Cát xây dựng', 'Cát', 'm3', 50.00, 10.000, 500.00, NULL),
    ('L014', 'I008', 1, 'Thép D10', 'Sắt', 'cây', 75.00, 120.000, 9000.00, NULL),
    ('L015', 'I009', 1, 'Gạch A', 'Gạch', 'viên', 99.99, 100.000, 9999.00, NULL),
    ('L016', 'I010', 1, 'Gạch A', 'Gạch', 'viên', 7.00, 100.000, 700.00, TIMESTAMP '2025-02-11 08:00:00');
