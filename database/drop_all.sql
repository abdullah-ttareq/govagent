-- ============================================================
-- GovAgent - حذف كل جداول المخطط (للتطوير فقط)
--
-- الغرض: إعادة تشغيل schema.sql على قاعدة صارت غير نظيفة.
-- الترتيب معكوس لترتيب الإنشاء بسبب المفاتيح الأجنبية.
--
-- ⚠️ هذا الملف يحذف البيانات نهائيًا. لا تشغّله على قاعدة إنتاج.
--
-- كل أمر مغلّف بـPL/SQL ليتجاهل خطأ "الجدول غير موجود" (ORA-00942)،
-- فيعمل الملف على قاعدة ناقصة أو نظيفة دون توقف.
-- ============================================================

BEGIN
    FOR t IN (
        SELECT table_name FROM (
            SELECT 'AUDIT_LOGS'      AS table_name, 1 AS drop_order FROM dual
            UNION ALL SELECT 'MODEL_SETTINGS',   2 FROM dual
            UNION ALL SELECT 'DOCUMENT_CHUNKS',  3 FROM dual
            UNION ALL SELECT 'FILES',            4 FROM dual
            UNION ALL SELECT 'MESSAGES',         5 FROM dual
            UNION ALL SELECT 'CONVERSATIONS',    6 FROM dual
            UNION ALL SELECT 'SUBSCRIPTIONS',    7 FROM dual
            UNION ALL SELECT 'USERS',            8 FROM dual
            UNION ALL SELECT 'ORGANIZATIONS',    9 FROM dual
        ) ORDER BY drop_order
    ) LOOP
        BEGIN
            EXECUTE IMMEDIATE 'DROP TABLE ' || t.table_name || ' CASCADE CONSTRAINTS PURGE';
            DBMS_OUTPUT.PUT_LINE('dropped: ' || t.table_name);
        EXCEPTION
            WHEN OTHERS THEN
                -- ORA-00942: الجدول غير موجود أصلًا — تجاهل وأكمل.
                IF SQLCODE != -942 THEN
                    RAISE;
                END IF;
        END;
    END LOOP;
END;
/
