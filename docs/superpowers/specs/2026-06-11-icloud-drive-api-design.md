# iCloud Drive API Design

## Goal

Add authenticated file-management endpoints to Mac Agent Gateway for every app container and user document stored under `~/Library/Mobile Documents`.

## Scope

The API supports binary-safe file operations and non-recursive directory listing:

- List the Mobile Documents root or one directory.
- Read and stream a regular file.
- Create or fully replace a regular file from a raw request body.
- Rename or move a regular file.
- Delete a regular file.
- Expose independent read and write capability flags.

All API paths are relative to `~/Library/Mobile Documents`. This includes `com~apple~CloudDocs` and every application container beneath the Mobile Documents root.

Out of scope:

- Creating, moving, renaming, or deleting directories.
- Recursive directory listing or recursive deletion.
- Partial-content updates or byte-range writes.
- Copy operations.
- Sharing links, version history, conflict resolution, or explicit iCloud synchronization controls.
- Access outside `~/Library/Mobile Documents`.

## API

Add a router mounted at `/v1/icloud`.

### List Root Or Directory

`GET /v1/icloud`

Lists the immediate children of `~/Library/Mobile Documents`.

`GET /v1/icloud/{path:path}`

When `path` identifies a directory, returns its immediate children. Directory listing is not recursive.

Directory response:

```json
{
  "path": "com~apple~CloudDocs/Projects",
  "entries": [
    {
      "path": "com~apple~CloudDocs/Projects/report.pdf",
      "name": "report.pdf",
      "kind": "file",
      "size": 12345,
      "modified_at": "2026-06-11T12:00:00-07:00"
    }
  ]
}
```

Entries are sorted by name using case-insensitive comparison for deterministic responses. `kind` is one of `file`, `directory`, `symlink`, or `other`. Symlink entries may be reported by a parent directory listing, but clients cannot traverse, read, update, move, or delete them. `size` is populated only for regular files. Metadata that cannot be read is returned as `null` rather than failing the entire listing.

### Read File

`GET /v1/icloud/{path:path}`

When `path` identifies a regular file, streams the raw file bytes. The response uses a media type inferred from the filename and falls back to `application/octet-stream`. Standard file response headers include content length and last-modified time when available.

Opening a locally evicted iCloud file may cause macOS to download it. The gateway does not directly control iCloud download or synchronization state.

### Create Or Replace File

`PUT /v1/icloud/{path:path}`

Consumes the raw request body as file bytes. The operation creates the file when it does not exist and fully replaces it when it does. Binary content is accepted without JSON or base64 encoding.

The destination parent directory must already exist. The target cannot be the Mobile Documents root, a directory, a symlink, or another non-regular filesystem object. Writes use a temporary file in the destination directory followed by atomic replacement so an interrupted upload does not leave a partially written destination. Temporary files are removed after failed requests.

Returns `201 Created` for a new file and `200 OK` for a replacement. The response is the resulting file entry metadata.

### Rename Or Move File

`PATCH /v1/icloud/{path:path}`

Request body:

```json
{
  "destination": "com~apple~CloudDocs/Archive/report.pdf"
}
```

The source must be a regular file. `destination` is the complete relative destination path, including the final filename, so the same operation supports both rename and move. The destination parent directory must already exist. The destination must not already exist; clients use `PUT` when replacement is intentional. A destination equal to the source is rejected as an invalid no-op.

Returns the moved file's entry metadata.

### Delete File

`DELETE /v1/icloud/{path:path}`

Deletes one regular file and returns:

```json
{
  "status": "deleted",
  "path": "com~apple~CloudDocs/Archive/report.pdf"
}
```

Directories, symlinks, special files, and the Mobile Documents root cannot be deleted through this API.

## Models

Create `mag.models.icloud` with these Pydantic models.

`ICloudEntry`:

- `path: str`: path relative to the Mobile Documents root.
- `name: str`: final path component.
- `kind: Literal["file", "directory", "symlink", "other"]`.
- `size: int | None`: byte size for regular files.
- `modified_at: datetime | None`: filesystem modification time.

`ICloudDirectoryListing`:

- `path: str`: relative directory path, or an empty string for the root.
- `entries: list[ICloudEntry]`.

`ICloudMove`:

- `destination: str`: complete relative destination file path.

`ICloudDeleteResponse`:

- `status: Literal["deleted"]`.
- `path: str`.

## Architecture

Follow the existing MAG router/model/service separation:

- `mag.routers.icloud` owns authentication, capability checks, HTTP request and response handling, and mapping service exceptions to HTTP status codes.
- `mag.services.icloud_drive` owns root-relative path validation and all filesystem operations.
- `mag.models.icloud` owns JSON request and metadata response contracts.
- `mag.config` adds iCloud read/write settings and advertises them through `/v1/capabilities`.
- `mag.main` mounts the router and includes iCloud Drive in application metadata and startup capability logging.

The service is represented by an `ICloudDriveService` with a default root of `Path("~/Library/Mobile Documents").expanduser()`. Tests instantiate the service with a temporary root; production does not expose a setting that can redirect access elsewhere.

The router passes `Request.stream()` to the service for `PUT`, avoiding buffering entire files in memory. File reads use a streaming file response. Directory results and mutation results use Pydantic response models.

## Path Safety

Every client-supplied path must pass one shared validation routine before filesystem access:

- Interpret paths as POSIX-style paths relative to the Mobile Documents root.
- Reject absolute paths.
- Reject empty mutation paths.
- Reject `.` and `..` path components.
- Reject NUL bytes and malformed paths.
- Confirm the lexical destination remains beneath the configured root.
- Inspect every existing component with non-following metadata calls and reject the path if any component is a symbolic link.
- For a new `PUT` destination, validate every existing parent component and require the immediate parent to be a real directory.
- For `PATCH`, independently validate the source, destination, and destination parent.

The service never uses `Path.resolve()` as permission to follow a symlink. Symlink detection is explicit and occurs before each operation. Operations are limited to regular files and real directories so FIFOs, sockets, devices, aliases represented as symlinks, and other special entries cannot be opened as files.

## Capabilities

Add settings enabled by default:

- `MAG_ICLOUD_READ=true`
- `MAG_ICLOUD_WRITE=true`

Add an `icloud` object to `/v1/capabilities`:

```json
{
  "icloud": {
    "read": true,
    "write": true
  }
}
```

Capability requirements:

- `icloud.read`: root listing, directory listing, and file reads.
- `icloud.write`: file create/replace, rename/move, and delete.

All endpoints continue to require the existing `X-API-Key` authentication dependency.

## Error Handling

Use stable HTTP status codes with structured `detail` objects:

- `400 Bad Request`: absolute/traversal paths, empty mutation paths, source and destination equality, unsupported filesystem object types, directory mutation attempts, or missing/non-directory destination parents.
- `403 Forbidden`: disabled capabilities, symbolic-link traversal, or filesystem permission failures.
- `404 Not Found`: missing read, move source, or delete target.
- `409 Conflict`: a `PATCH` destination already exists.
- `507 Insufficient Storage`: the filesystem reports insufficient space during `PUT`.
- `500 Internal Server Error`: other filesystem failures, without exposing unrelated absolute paths or stack traces.

Errors may identify the client-supplied relative path but must not return absolute home-directory paths. Failed `PUT` operations must clean up their temporary file.

## Concurrency And Consistency

`PUT` writes to a temporary file in the destination directory and atomically replaces the target only after the complete request body is persisted. Concurrent `PUT` requests follow last-completed-write-wins behavior.

`PATCH` checks that the destination does not exist immediately before rename and returns `409` when it does. The API does not provide cross-process locking; normal filesystem race behavior remains possible when another local process modifies the same path concurrently.

Directory listings are point-in-time best-effort views. An entry changed by iCloud or another local process during listing may be absent or may contain `null` metadata.

## Tests

Use TDD and temporary directories. Tests must not read or mutate the developer's real `~/Library/Mobile Documents` tree.

Model coverage:

- Move requests require a non-empty destination.
- Entry and directory listing response models serialize expected metadata.

Service coverage:

- Root and nested directory listings are non-recursive and deterministically sorted.
- Listing labels regular files, directories, symlinks, and other entries correctly.
- Binary files can be written, read, replaced, moved, and deleted.
- `PUT` creates missing files and replaces existing regular files atomically.
- Failed streamed writes remove temporary files and preserve an existing destination.
- Missing parents and directory targets are rejected.
- `PATCH` supports rename and move but never overwrites an existing destination.
- Directory deletion and all other directory mutations are rejected.
- Absolute paths, traversal components, and root mutation attempts are rejected.
- A symlink in the target or any existing parent component is rejected for every direct operation.
- Special files are rejected rather than read or mutated.
- Service exceptions do not expose the absolute temporary root.

Router coverage:

- Every route requires the API key.
- Read and write capabilities are enforced independently.
- Root and directory `GET` requests return JSON listings.
- File `GET` requests return exact raw binary bytes and an appropriate content type.
- `PUT` returns `201` for create and `200` for replacement.
- `PATCH` validates JSON and returns moved metadata.
- `DELETE` returns the documented status response.
- Service error categories map to the documented HTTP status codes.
- `/v1/capabilities` includes the iCloud capability object.

Run the full test suite and Ruff after focused iCloud tests pass.

## Documentation

Update `.env.example` with the iCloud capability flags. Update README feature, configuration, capabilities, endpoint, security, and limitation sections. Document that API paths begin below `~/Library/Mobile Documents`, that this exposes app containers as well as `com~apple~CloudDocs`, and that symbolic links and directory mutations are intentionally blocked.

No runtime dependency is required beyond Python's standard library and the project's existing FastAPI stack.

## Acceptance Criteria

- Authenticated clients can list every real directory below `~/Library/Mobile Documents` one level at a time.
- Authenticated clients can stream any regular file below that root, including binary files.
- Authenticated clients can create, fully replace, rename, move, and delete regular files below that root.
- Directory mutations, recursive operations, special-file access, path traversal, and symbolic-link traversal are rejected.
- Read and write operations can be disabled independently and are advertised by `/v1/capabilities`.
- Uploads do not buffer the complete body in memory and do not expose partial destination files.
- Tests pass without touching the real Mobile Documents directory.
- README and `.env.example` describe the API and its security boundary.
