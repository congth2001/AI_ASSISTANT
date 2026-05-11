# Face Recognition Service - Clean Architecture

## 🏗️ Cấu trúc Project

Project được tổ chức theo **Clean Architecture** với các layer rõ ràng và tuân thủ **SOLID principles**.

```
face-recognition-service/
├── src/                           # Source code chính
│   ├── domain/                    # Domain Layer - Pure business logic
│   │   ├── entities/              # Business entities
│   │   │   ├── user.py           # User entity
│   │   │   ├── face.py           # Face entity
│   │   │   ├── person.py         # Person entity
│   │   │   ├── face_vector.py    # FaceVector entity
│   │   │   ├── face_match.py     # FaceMatch entity
│   │   │   ├── constants.py      # Domain constants
│   │   │   └── errors.py         # Domain exceptions
│   │   ├── repositories/          # Repository interfaces
│   │   │   ├── face_repository.py
│   │   │   ├── person_repository.py
│   │   │   └── vector_repository.py
│   │   ├── value_objects/         # Value objects (future)
│   │   └── exceptions/            # Domain exceptions (future)
│   ├── application/               # Application Layer - Use cases
│   │   ├── use_cases/             # Business use cases
│   │   │   ├── detect_faces_use_case.py
│   │   │   ├── register_face_use_case.py
│   │   │   ├── search_faces_use_case.py
│   │   │   └── delete_face_use_case.py
│   │   ├── services/              # Application services
│   │   │   ├── face_detection_service.py
│   │   │   ├── face_encoding_service.py
│   │   │   └── face_matching_service.py
│   │   └── interfaces/            # Application interfaces (future)
│   ├── infrastructure/            # Infrastructure Layer
│   │   ├── repositories/          # Repository implementations
│   │   │   ├── mongo_face_repository.py
│   │   │   ├── mongo_person_repository.py
│   │   │   └── milvus_vector_repository.py
│   │   ├── external_services/     # External service implementations (future)
│   │   └── database/              # Database configurations (future)
│   └── presentation/              # Presentation Layer
│       ├── api/                   # FastAPI routers
│       │   ├── face.py           # Face API routes
│       │   └── person.py         # Person API routes
│       ├── controllers/           # Controllers
│       │   ├── face_controller.py
│       │   └── person_controller.py
│       ├── dto/                   # Data Transfer Objects
│       │   ├── face_dto.py
│       │   └── person_dto.py
│       ├── dependencies.py        # FastAPI dependencies
│       └── session_resource_factory.py
├── config/                        # Configuration files
├── tests/                         # Test files (future)
├── main.py                        # Application entry point
└── requirements.txt               # Dependencies
```

## 🎯 **Clean Architecture Layers**

### 1. **Domain Layer** (`src/domain/`)
- **Entities**: Pure business objects không phụ thuộc vào framework
- **Repositories**: Interfaces cho data access
- **Value Objects**: Immutable objects
- **Exceptions**: Domain-specific exceptions

### 2. **Application Layer** (`src/application/`)
- **Use Cases**: Business logic chính
- **Services**: Application services
- **Interfaces**: Application interfaces

### 3. **Infrastructure Layer** (`src/infrastructure/`)
- **Repositories**: Concrete implementations của domain interfaces
- **External Services**: Third-party service implementations
- **Database**: Database configurations
- **Utils**: Infrastructure utilities (logging, singleton, etc.)

### 4. **Presentation Layer** (`src/presentation/`)
- **API**: FastAPI routers
- **Controllers**: Request/Response handling
- **DTOs**: Data Transfer Objects
- **Dependencies**: FastAPI dependency injection

## 🔄 **Dependency Flow**

```
Presentation → Application → Domain
     ↓              ↓
Infrastructure → Application
```

- **Presentation** depends on **Application** và **Domain**
- **Application** depends on **Domain** only
- **Infrastructure** depends on **Domain** và **Application**
- **Domain** không depend on bất kỳ layer nào

## ✅ **SOLID Principles**

### 1. **Single Responsibility Principle (SRP)**
- Mỗi class có một trách nhiệm duy nhất
- `FaceController` chỉ handle face operations
- `PersonController` chỉ handle person operations

### 2. **Open/Closed Principle (OCP)**
- Có thể mở rộng mà không sửa code cũ
- Thêm provider mới cho face detection
- Thêm repository implementation mới

### 3. **Liskov Substitution Principle (LSP)**
- Các subclass có thể thay thế base class
- `MongoFaceRepository` có thể thay thế `FaceRepository`

### 4. **Interface Segregation Principle (ISP)**
- Interfaces nhỏ và chuyên biệt
- `FaceRepository`, `PersonRepository`, `VectorRepository` riêng biệt

### 5. **Dependency Inversion Principle (DIP)**
- Depend vào abstractions, không phải concrete classes
- Use cases depend on repository interfaces, không phải implementations

## 🚀 **Benefits**

### 1. **Maintainability**
- Code rõ ràng, dễ hiểu
- Mỗi layer có trách nhiệm riêng biệt

### 2. **Testability**
- Có thể test từng layer độc lập
- Dễ dàng mock dependencies

### 3. **Scalability**
- Dễ dàng thêm features mới
- Có thể thay đổi implementation mà không ảnh hưởng business logic

### 4. **Flexibility**
- Có thể thay đổi database, framework mà không ảnh hưởng domain
- Dễ dàng migrate sang technology khác

## 📝 **Naming Conventions**

- **Entities**: `User`, `Face`, `Person`
- **Use Cases**: `DetectFacesUseCase`, `RegisterFaceUseCase`
- **Services**: `FaceDetectionService`, `FaceEncodingService`
- **Repositories**: `FaceRepository`, `MongoFaceRepository`
- **Controllers**: `FaceController`, `PersonController`
- **DTOs**: `FaceDto`, `PersonDto`

## 🔧 **Development Guidelines**

### 1. **Adding New Features**
1. Define domain entities
2. Create repository interfaces
3. Implement use cases
4. Create application services
5. Implement infrastructure
6. Create presentation layer

### 2. **Testing Strategy**
- Unit tests cho domain entities
- Integration tests cho use cases
- End-to-end tests cho API endpoints

### 3. **Code Organization**
- Mỗi file một class/interface
- Group related functionality
- Use meaningful names
- Keep functions small and focused

## 📚 **References**

- [Clean Architecture by Robert C. Martin](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [SOLID Principles](https://en.wikipedia.org/wiki/SOLID)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
