# Database Extension Setup: pgvector

This document describes the manual installation process of the `pgvector` extension for PostgreSQL 17 on Windows environments.

![PostgreSQL 17 Logo](image.png)

## 1. Prerequisites
- **PostgreSQL Version**: 17.x (x64)
- **Operating System**: Windows 10/11
- **Access Level**: Administrator (require for file system operations)

## 2. Resources
- **Source**: [pgvector_pgsql_windows](https://github.com/andreiramani/pgvector_pgsql_windows)
- **Artifacts**: Pre-built binaries (include, lib, share)

![Folders](image-1.png)

## 3. Installation Steps
### Step 1: File Distribution
Extract the downloaded binaries and copy the contents to the PostgreSQL installation directory (Default: `C:\Program Files\PostgreSQL\17`):

| Source Folder | Destination Path | Target Files |
| :--- | :--- | :--- |
| `lib/` | `...\17\lib` | `vector.dll` |
| `share/extension/` | `...\17\share\extension` | `vector.control`, `vector--*.sql` |
| `include/` | `...\17\include\server\extension\vector` | `vector.h`, etc. |

### Step 2: Service Restart
To load the new library, restart the PostgreSQL service:
1. Open **Services** (Press `Win + R`, type `services.msc`, and hit Enter).
2. Locate **postgresql-x64-17**.
3. Right-click and select **Restart** or Click **Restart** on the left panel.

![Service Restart](image-2.png)

### Step 3: Activation
Reopen PgAdmin and execute the following SQL command in your database (e.g., via pgAdmin or psql):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

![Activation](image-3.png)
![Extension](image-4.png)

## 4. Verification
Run the following query to confirm the installation:
```sql
SELECT extversion FROM pg_extension WHERE extname = 'vector';
```
Expected Output: the version you installed.