"""Phase 2 Schema 语义文档 CRUD：双粒度检索（pgvector 直查）+ upsert + 补 embedding。

改造标记 SCHEMA-DOC：
- 检索口径与原 calc_table_embedding 对齐（top TABLE_EMBEDDING_COUNT、无阈值），
  仅换文本来源：DDL embedding（core_table.embedding）→ 业务语义文档 embedding。
- 返回空清单 = 调用方回退原路径（互为回退，SCHEMA_DOC_ENABLED 默认 False）。
"""
import traceback
from datetime import datetime
from typing import List

from sqlalchemy import select, text, update

from apps.ai_model.embedding import EmbeddingModelCache
from apps.datasource.models.datasource import ColumnMetadata, SchemaDocument, TableMetadata
from common.core.config import settings

schema_doc_table_sql = """
SELECT object_key AS table_name,
       (1 - (embedding <=> :embedding_array)) AS similarity
FROM schema_document
WHERE ds_id = :ds_id AND object_type = 'TABLE'
  AND embedding IS NOT NULL AND document_text IS NOT NULL
ORDER BY embedding <=> :embedding_array
LIMIT :top
"""

schema_doc_column_sql = """
SELECT split_part(object_key, '.', 1) AS table_name,
       (1 - (embedding <=> :embedding_array)) AS similarity
FROM schema_document
WHERE ds_id = :ds_id AND object_type = 'COLUMN'
  AND embedding IS NOT NULL AND document_text IS NOT NULL
ORDER BY embedding <=> :embedding_array
LIMIT :top
"""


def select_schema_doc_tables(session, ds_id: int, question: str) -> List[str]:
    """TABLE/COLUMN 双粒度检索，返回合并去重的表名清单（保序：TABLE 先、COLUMN 宿主表后）。

    空清单表示不可用（未配置/无文档/embedding 失败），调用方应回退原 DDL embedding 路径。
    """
    if not question or not ds_id or not settings.EMBEDDING_ENABLED:
        return []
    try:
        model = EmbeddingModelCache.get_model()
        q_embedding = model.embed_query(question)
        params = {'embedding_array': str(q_embedding), 'ds_id': ds_id,
                  'top': settings.TABLE_EMBEDDING_COUNT}
        table_rows = session.execute(text(schema_doc_table_sql), params).fetchall()
        column_rows = session.execute(text(schema_doc_column_sql), params).fetchall()
        merged: List[str] = []
        for row in list(table_rows) + list(column_rows):
            name = row[0]
            if name and name not in merged:
                merged.append(name)
        return merged
    except Exception:
        traceback.print_exc()
        return []


def run_fill_empty_schema_doc_embeddings(session_maker):
    """补齐空 embedding（对 schema_document.document_text）。"""
    try:
        if not settings.EMBEDDING_ENABLED:
            return
        session = session_maker()
        results = session.execute(
            select(SchemaDocument.id).where(SchemaDocument.embedding.is_(None))).scalars().all()
        save_embeddings(session_maker, results)
    except Exception:
        traceback.print_exc()
    finally:
        session_maker.remove()


def save_embeddings(session_maker, ids: List[int]):
    if not settings.EMBEDDING_ENABLED:
        return
    if not ids or len(ids) == 0:
        return
    try:
        session = session_maker()
        _list = session.query(SchemaDocument).filter(SchemaDocument.id.in_(ids)).all()
        _docs = [item.document_text or "" for item in _list]
        if not _docs:
            return

        model = EmbeddingModelCache.get_model()
        results = model.embed_documents(_docs)

        for index in range(len(results)):
            stmt = update(SchemaDocument).where(SchemaDocument.id == _list[index].id).values(
                embedding=results[index])
            session.execute(stmt)
            session.commit()
    except Exception:
        traceback.print_exc()
    finally:
        session_maker.remove()


def upsert_schema_documents(session, ds_id: int, rows: List[dict]) -> List[int]:
    """按 (ds_id, object_type, object_key) 幂等 upsert；文本变更时重置 embedding 待重算。

    返回发生新增/变更的 id 列表（供调用方补 embedding）。
    """
    existing = {(r.object_type, r.object_key): r
                for r in session.query(SchemaDocument).filter(SchemaDocument.ds_id == ds_id).all()}
    changed_ids: List[int] = []
    for row in rows:
        object_type = (row.get('object_type') or '').strip().upper()
        object_key = (row.get('object_key') or '').strip()
        document_text = (row.get('document_text') or '').strip()
        if object_type not in ('TABLE', 'COLUMN') or not object_key or not document_text:
            continue
        rec = existing.get((object_type, object_key))
        if rec is None:
            rec = SchemaDocument(ds_id=ds_id, object_type=object_type, object_key=object_key,
                                 document_text=document_text, embedding=None,
                                 create_time=datetime.now())
            session.add(rec)
            session.flush()
            changed_ids.append(rec.id)
        elif rec.document_text != document_text:
            rec.document_text = document_text
            rec.embedding = None
            changed_ids.append(rec.id)
    session.commit()
    return changed_ids


def upsert_table_metadata(session, ds_id: int, table_names: List[str]) -> int:
    """table_metadata 只补缺失行（description 为 G5 预留，不覆盖已有行）。"""
    if not table_names:
        return 0
    existing = {r.table_name for r in session.query(TableMetadata).filter(
        TableMetadata.ds_id == ds_id).all()}
    created = 0
    for name in dict.fromkeys(table_names):  # 批次内去重（调用方可能传入含重复的宿主表名）
        if not name or name in existing:
            continue
        session.add(TableMetadata(ds_id=ds_id, table_name=name, description=None,
                                  create_time=datetime.now()))
        existing.add(name)  # 同批次后续同名不再插入
        created += 1
    session.commit()
    return created


def upsert_column_metadata(session, ds_id: int, pairs: List[tuple]) -> int:
    """column_metadata 只补缺失行（alias/description 为预留，不覆盖已有行）。

    pairs: [(table_name, field_name), ...]
    """
    if not pairs:
        return 0
    existing = {(r.table_name, r.field_name) for r in session.query(ColumnMetadata).filter(
        ColumnMetadata.ds_id == ds_id).all()}
    created = 0
    for table_name, field_name in dict.fromkeys(pairs):  # 批次内去重
        if not table_name or not field_name or (table_name, field_name) in existing:
            continue
        session.add(ColumnMetadata(ds_id=ds_id, table_name=table_name, field_name=field_name,
                                   alias=[], description=None, create_time=datetime.now()))
        existing.add((table_name, field_name))
        created += 1
    session.commit()
    return created
