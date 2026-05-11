#!/usr/bin/env python3
"""
Database Seeding Script for Business Chatbot
Creates initial data for testing and development
"""
import asyncio
from datetime import datetime, timedelta
import uuid
import random

from config.settings import settings
from config.container import container


async def seed_business_data():
    """Seed sample business data"""
    print("Seeding business data...")

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get use case
    ingest_use_case = container.ingest_data_use_case()

    # Sample data
    sample_data = [
        # Revenue data
        {
            'id': str(uuid.uuid4()),
            'data_type': 'revenue',
            'value': 15000.00,
            'date': (datetime.now() - timedelta(days=30)).date().isoformat(),
            'category': 'sales',
            'subcategory': 'online',
            'metadata': {'source': 'seed_data', 'description': 'Monthly online sales'}
        },
        {
            'id': str(uuid.uuid4()),
            'data_type': 'revenue',
            'value': 8500.00,
            'date': (datetime.now() - timedelta(days=30)).date().isoformat(),
            'category': 'sales',
            'subcategory': 'in_store',
            'metadata': {'source': 'seed_data', 'description': 'Monthly in-store sales'}
        },
        {
            'id': str(uuid.uuid4()),
            'data_type': 'profit',
            'value': 3200.00,
            'date': (datetime.now() - timedelta(days=30)).date().isoformat(),
            'category': 'net_profit',
            'metadata': {'source': 'seed_data', 'description': 'Monthly net profit'}
        },
        # Customer data
        {
            'id': str(uuid.uuid4()),
            'data_type': 'customer',
            'value': 1,  # Count
            'date': (datetime.now() - timedelta(days=15)).date().isoformat(),
            'category': 'new_customers',
            'metadata': {'source': 'seed_data', 'customer_id': 'CUST_001', 'segment': 'vip'}
        },
        {
            'id': str(uuid.uuid4()),
            'data_type': 'inventory',
            'value': 150,
            'date': datetime.now().date().isoformat(),
            'category': 'electronics',
            'subcategory': 'laptops',
            'metadata': {'source': 'seed_data', 'description': 'Current laptop inventory'}
        }
    ]

    # Ingest data
    results = []
    for data in sample_data:
        try:
            result = await ingest_use_case.execute(data)
            results.append(result)
            print(f"✓ Seeded {data['data_type']} data: {data['value']}")
        except Exception as e:
            print(f"✗ Failed to seed data: {e}")
            results.append({'success': False, 'error': str(e)})

    successful = sum(1 for r in results if r.get('success', False))

    return {
        'total_seeded': len(sample_data),
        'successful': successful,
        'failed': len(sample_data) - successful
    }


async def seed_knowledge_base():
    """Seed sample knowledge base documents"""
    print("Seeding knowledge base...")

    # Configure container
    container.config.from_dict(settings.dict())
    container.database_url.override(settings.database.url)

    # Get services
    embedding_service = container.embedding_service()
    vector_db = container.vector_db()

    # Sample knowledge base content
    knowledge_docs = [
        {
            'id': 'kb_store_policies',
            'content': """
            STORE POLICIES AND PROCEDURES

            1. CUSTOMER SERVICE
            - All customers receive personalized service
            - Returns accepted within 30 days with receipt
            - Customer satisfaction is our top priority

            2. SALES PROCEDURES
            - All sales must be recorded in the system
            - Discounts require manager approval
            - Cash transactions limited to $500

            3. INVENTORY MANAGEMENT
            - Daily inventory counts required
            - Stock alerts when items below 10 units
            - Seasonal stock reviews quarterly
            """,
            'metadata': {
                'source': 'knowledge_base',
                'category': 'policies',
                'title': 'Store Policies and Procedures'
            }
        },
        {
            'id': 'kb_product_info',
            'content': """
            PRODUCT INFORMATION

            ELECTRONICS DEPARTMENT:
            - Laptops: High-performance models from major brands
            - Accessories: Cables, cases, and peripherals
            - Warranties: Extended coverage available

            CLOTHING DEPARTMENT:
            - Seasonal collections updated quarterly
            - Size ranges: XS to 4XL
            - Material quality: Premium fabrics only

            HOME GOODS:
            - Furniture: Custom orders available
            - Decor: Seasonal and holiday items
            - Appliances: Energy-efficient models
            """,
            'metadata': {
                'source': 'knowledge_base',
                'category': 'products',
                'title': 'Product Information'
            }
        },
        {
            'id': 'kb_business_goals',
            'content': """
            BUSINESS GOALS AND TARGETS

            Q4 2024 OBJECTIVES:
            - Revenue Target: $500,000
            - Customer Acquisition: 200 new customers
            - Profit Margin: 15% minimum
            - Customer Satisfaction: 95% rating

            LONG-TERM GOALS:
            - Expand to 3 new locations
            - Launch e-commerce platform
            - Implement loyalty program
            - Achieve carbon neutrality by 2026
            """,
            'metadata': {
                'source': 'knowledge_base',
                'category': 'strategy',
                'title': 'Business Goals and Targets'
            }
        }
    ]

    # Store documents
    results = []
    for doc in knowledge_docs:
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
                print(f"✓ Seeded knowledge document: {doc['id']}")
                results.append({'success': True, 'id': doc['id']})
            else:
                print(f"✗ Failed to seed document: {doc['id']}")
                results.append({'success': False, 'id': doc['id']})

        except Exception as e:
            print(f"✗ Error seeding document {doc['id']}: {e}")
            results.append({'success': False, 'id': doc['id'], 'error': str(e)})

    successful = sum(1 for r in results if r.get('success', False))

    return {
        'total_seeded': len(knowledge_docs),
        'successful': successful,
        'failed': len(knowledge_docs) - successful
    }


async def main():
    """Main seeding function"""
    print("Starting database seeding...")

    results = {}

    # Seed business data
    results['business_data'] = await seed_business_data()

    # Seed knowledge base
    results['knowledge_base'] = await seed_knowledge_base()

    # Print summary
    print("\n" + "="*50)
    print("SEEDING SUMMARY")
    print("="*50)

    total_processed = 0
    total_successful = 0

    for operation, result in results.items():
        print(f"\n{operation.upper()}:")
        print(f"  Total seeded: {result['total_seeded']}")
        print(f"  Successful: {result['successful']}")
        print(f"  Failed: {result['failed']}")

        total_processed += result['total_seeded']
        total_successful += result['successful']

    print(f"\nOVERALL:")
    print(f"  Total processed: {total_processed}")
    print(f"  Total successful: {total_successful}")
    print(f"  Total failed: {total_processed - total_successful}")

    print("\nSeeding completed!")


if __name__ == "__main__":
    asyncio.run(main())