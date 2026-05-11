#!/usr/bin/env python3
"""
Data Ingestion Script for Business Chatbot
Ingests business data from CSV files into the system
"""
import asyncio
import csv
import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import uuid

from config.settings import settings
from config.container import container


async def ingest_csv_data(csv_file_path: str, data_type: str) -> Dict[str, Any]:
    """Ingest data from CSV file"""
    print(f"Ingesting data from {csv_file_path}...")

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get use case
    ingest_use_case = container.ingest_data_use_case()

    # Read CSV file
    data_records = []
    with open(csv_file_path, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            # Convert row to business data format
            data_record = {
                'id': str(uuid.uuid4()),
                'data_type': data_type,
                'value': float(row.get('value', 0)),
                'date': datetime.fromisoformat(row['date']).date().isoformat(),
                'category': row.get('category'),
                'subcategory': row.get('subcategory'),
                'metadata': {
                    'source': 'csv_ingestion',
                    'filename': Path(csv_file_path).name,
                    'original_data': row
                }
            }
            data_records.append(data_record)

    # Ingest data
    results = []
    for record in data_records:
        try:
            result = await ingest_use_case.execute(record)
            results.append(result)
            print(f"✓ Ingested record {record['id']}")
        except Exception as e:
            print(f"✗ Failed to ingest record {record['id']}: {e}")
            results.append({'success': False, 'error': str(e)})

    successful = sum(1 for r in results if r.get('success', False))

    return {
        'total_processed': len(data_records),
        'successful': successful,
        'failed': len(data_records) - successful,
        'results': results
    }


async def ingest_knowledge_base(directory_path: str) -> Dict[str, Any]:
    """Ingest knowledge base documents"""
    print(f"Ingesting knowledge base from {directory_path}...")

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get services
    embedding_service = container.embedding_service()
    vector_db = container.vector_db()

    knowledge_path = Path(directory_path)
    documents = []

    # Read all text/markdown files
    for file_path in knowledge_path.rglob('*'):
        if file_path.suffix.lower() in ['.txt', '.md', '.pdf']:
            try:
                if file_path.suffix.lower() == '.pdf':
                    # TODO: Add PDF parsing
                    continue

                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()

                # Split into chunks (simple approach)
                chunks = split_text_into_chunks(content, chunk_size=1000, overlap=200)

                for i, chunk in enumerate(chunks):
                    doc_id = f"{file_path.stem}_chunk_{i}"
                    documents.append({
                        'id': doc_id,
                        'content': chunk,
                        'metadata': {
                            'source': 'knowledge_base',
                            'filename': file_path.name,
                            'filepath': str(file_path),
                            'chunk_index': i
                        }
                    })

            except Exception as e:
                print(f"Error reading {file_path}: {e}")

    # Store in vector database
    results = []
    for doc in documents:
        try:
            # Generate embedding
            embedding = await embedding_service.generate_embedding(doc['content'])

            # Store in vector DB
            success = await vector_db.store_embedding(
                doc['id'],
                embedding,
                doc['metadata']
            )

            if success:
                print(f"✓ Stored document chunk {doc['id']}")
                results.append({'success': True, 'id': doc['id']})
            else:
                print(f"✗ Failed to store document chunk {doc['id']}")
                results.append({'success': False, 'id': doc['id']})

        except Exception as e:
            print(f"✗ Error processing document {doc['id']}: {e}")
            results.append({'success': False, 'id': doc['id'], 'error': str(e)})

    successful = sum(1 for r in results if r.get('success', False))

    return {
        'total_processed': len(documents),
        'successful': successful,
        'failed': len(documents) - successful,
        'results': results
    }


def split_text_into_chunks(text: str, chunk_size: int = 1000, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks"""
    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        # Find a good breaking point (sentence end)
        if end < len(text):
            # Look for sentence endings within the last 100 characters
            search_end = min(end + 100, len(text))
            sentence_end = text.rfind('.', end, search_end)
            if sentence_end != -1:
                end = sentence_end + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # Move start position with overlap
        start = end - overlap

        # Ensure we don't get stuck
        if start >= len(text) - overlap:
            break

    return chunks


async def main():
    """Main ingestion function"""
    import argparse

    parser = argparse.ArgumentParser(description='Ingest data into Business Chatbot')
    parser.add_argument('--csv', help='Path to CSV file for business data')
    parser.add_argument('--data-type', default='revenue', help='Type of data in CSV')
    parser.add_argument('--knowledge-base', help='Path to knowledge base directory')

    args = parser.parse_args()

    results = {}

    if args.csv:
        results['csv_ingestion'] = await ingest_csv_data(args.csv, args.data_type)

    if args.knowledge_base:
        results['knowledge_base_ingestion'] = await ingest_knowledge_base(args.knowledge_base)

    # Print summary
    print("\n" + "="*50)
    print("INGESTION SUMMARY")
    print("="*50)

    for operation, result in results.items():
        print(f"\n{operation.upper()}:")
        print(f"  Total processed: {result['total_processed']}")
        print(f"  Successful: {result['successful']}")
        print(f"  Failed: {result['failed']}")

    print("\nIngestion completed!")


if __name__ == "__main__":
    asyncio.run(main())