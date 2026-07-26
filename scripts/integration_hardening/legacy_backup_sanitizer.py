"""Streaming, side-effect-free validation for offline MySQL logical backups."""

from __future__ import annotations

import codecs
import hashlib
import re
from collections import Counter
from typing import Any, BinaryIO, Iterable


class LegacyBackupSanitizationError(RuntimeError):
    """Raised when an offline backup cannot be proven safe for protected restore."""


_LOWER_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CANONICAL_MYSQL_VERSION_RE = re.compile(
    r"([1-9][0-9]?)\.(0|[1-9][0-9]?)\.(0|[1-9][0-9]?)\Z"
)
_IDENTIFIER = r"(?:`(?:``|\\[^\r\n]|[^`\\])+`|[A-Za-z_][A-Za-z0-9_$]*)"
_META_COMMANDS = frozenset(
    {
        "CHARSET",
        "CONNECT",
        "DELIMITER",
        "EDIT",
        "EGO",
        "EXIT",
        "GO",
        "HELP",
        "NOPAGER",
        "NOTEE",
        "PAGER",
        "PRINT",
        "PROMPT",
        "QUIT",
        "REHASH",
        "SOURCE",
        "STATUS",
        "SYSTEM",
        "TEE",
    }
)
_FORBIDDEN_CODE_PATTERNS = (
    re.compile(r"\b(?:CREATE|DROP|ALTER)\s+(?:DATABASE|SCHEMA)\b", re.IGNORECASE),
    re.compile(r"\bUSE\b", re.IGNORECASE),
    re.compile(r"\b(?:CREATE|ALTER|DROP)\s+(?:USER|ROLE)\b", re.IGNORECASE),
    re.compile(r"\b(?:GRANT|REVOKE)\b", re.IGNORECASE),
    re.compile(r"\bSET\s+(?:@@\s*)?(?:GLOBAL|PERSIST|PERSIST_ONLY)\b", re.IGNORECASE),
    re.compile(r"\bDEFINER\b", re.IGNORECASE),
    re.compile(r"\b(?:TRIGGER|PROCEDURE|FUNCTION|EVENT)\b", re.IGNORECASE),
    re.compile(r"\bLOAD\s+DATA\b", re.IGNORECASE),
    re.compile(r"\bLOAD_FILE\s*\(", re.IGNORECASE),
    re.compile(r"\bINTO\s+(?:OUTFILE|DUMPFILE)\b", re.IGNORECASE),
    re.compile(r"\b(?:INSTALL|UNINSTALL)\s+(?:PLUGIN|COMPONENT)\b", re.IGNORECASE),
    re.compile(r"\bSHUTDOWN\b", re.IGNORECASE),
    re.compile(r"\b(?:DATA|INDEX)\s+DIRECTORY\b", re.IGNORECASE),
    re.compile(r"\bTABLESPACE\b", re.IGNORECASE),
)

_CREATE_TABLE_OPTION_PATTERNS = (
    (
        "engine",
        re.compile(r"ENGINE\s*=\s*(?:INNODB|MYISAM)\b", re.IGNORECASE),
    ),
    ("auto_increment", re.compile(r"AUTO_INCREMENT\s*=\s*[0-9]+\b", re.IGNORECASE)),
    (
        "default_charset",
        re.compile(
            r"DEFAULT\s+(?:CHARSET|CHARACTER\s+SET)\s*=\s*[A-Za-z0-9_]+\b",
            re.IGNORECASE,
        ),
    ),
    ("collate", re.compile(r"(?:DEFAULT\s+)?COLLATE\s*=\s*[A-Za-z0-9_]+\b", re.IGNORECASE)),
    (
        "row_format",
        re.compile(
            r"ROW_FORMAT\s*=\s*(?:DEFAULT|DYNAMIC|COMPACT|REDUNDANT|COMPRESSED)\b",
            re.IGNORECASE,
        ),
    ),
    ("key_block_size", re.compile(r"KEY_BLOCK_SIZE\s*=\s*[0-9]+\b", re.IGNORECASE)),
    (
        "stats_persistent",
        re.compile(r"STATS_PERSISTENT\s*=\s*(?:DEFAULT|0|1)\b", re.IGNORECASE),
    ),
    (
        "stats_auto_recalc",
        re.compile(r"STATS_AUTO_RECALC\s*=\s*(?:DEFAULT|0|1)\b", re.IGNORECASE),
    ),
    ("stats_sample_pages", re.compile(r"STATS_SAMPLE_PAGES\s*=\s*[0-9]+\b", re.IGNORECASE)),
    ("checksum", re.compile(r"CHECKSUM\s*=\s*(?:0|1)\b", re.IGNORECASE)),
    ("delay_key_write", re.compile(r"DELAY_KEY_WRITE\s*=\s*(?:0|1)\b", re.IGNORECASE)),
    (
        "pack_keys",
        re.compile(r"PACK_KEYS\s*=\s*(?:DEFAULT|0|1)\b", re.IGNORECASE),
    ),
)
_SET_ALLOWLIST = tuple(
    (kind, re.compile(pattern, re.IGNORECASE))
    for kind, pattern in (
        ("setup", r"SET\s+NAMES\s+(?:utf8|utf8mb4)"),
        ("setup", r"SET\s+@OLD_CHARACTER_SET_CLIENT\s*=\s*@@CHARACTER_SET_CLIENT"),
        ("setup", r"SET\s+@OLD_CHARACTER_SET_RESULTS\s*=\s*@@CHARACTER_SET_RESULTS"),
        ("setup", r"SET\s+@OLD_COLLATION_CONNECTION\s*=\s*@@COLLATION_CONNECTION"),
        ("setup", r"SET\s+@SAVED_CS_CLIENT\s*=\s*@@CHARACTER_SET_CLIENT"),
        ("teardown", r"SET\s+CHARACTER_SET_CLIENT\s*=\s*@OLD_CHARACTER_SET_CLIENT"),
        ("teardown", r"SET\s+CHARACTER_SET_RESULTS\s*=\s*@OLD_CHARACTER_SET_RESULTS"),
        ("teardown", r"SET\s+COLLATION_CONNECTION\s*=\s*@OLD_COLLATION_CONNECTION"),
        ("setup", r"SET\s+CHARACTER_SET_CLIENT\s*=\s*UTF8MB4"),
        ("teardown", r"SET\s+CHARACTER_SET_CLIENT\s*=\s*@SAVED_CS_CLIENT"),
        ("setup", r"SET\s+@OLD_TIME_ZONE\s*=\s*@@TIME_ZONE"),
        ("setup", r"SET\s+TIME_ZONE\s*=\s*'\+00:00'"),
        ("teardown", r"SET\s+TIME_ZONE\s*=\s*@OLD_TIME_ZONE"),
        (
            "setup",
            r"SET\s+@OLD_UNIQUE_CHECKS\s*=\s*@@UNIQUE_CHECKS\s*,\s*UNIQUE_CHECKS\s*=\s*0",
        ),
        ("teardown", r"SET\s+UNIQUE_CHECKS\s*=\s*@OLD_UNIQUE_CHECKS"),
        (
            "setup",
            r"SET\s+@OLD_FOREIGN_KEY_CHECKS\s*=\s*@@FOREIGN_KEY_CHECKS\s*,\s*FOREIGN_KEY_CHECKS\s*=\s*0",
        ),
        ("teardown", r"SET\s+FOREIGN_KEY_CHECKS\s*=\s*@OLD_FOREIGN_KEY_CHECKS"),
        (
            "sql_mode_normalize",
            r"SET\s+@OLD_SQL_MODE\s*=\s*@@SQL_MODE\s*,\s*SQL_MODE\s*=\s*'NO_AUTO_VALUE_ON_ZERO'",
        ),
        ("sql_mode_restore", r"SET\s+SQL_MODE\s*=\s*@OLD_SQL_MODE"),
        (
            "setup",
            r"SET\s+@OLD_SQL_NOTES\s*=\s*@@SQL_NOTES\s*,\s*SQL_NOTES\s*=\s*0",
        ),
        ("teardown", r"SET\s+SQL_NOTES\s*=\s*@OLD_SQL_NOTES"),
    )
)
_DATA_STATEMENT_KEYWORDS = frozenset(
    {"DROP", "CREATE", "ALTER", "INSERT", "LOCK", "UNLOCK", "START", "COMMIT"}
)


class _CharacterStream:
    def __init__(self, characters: Iterable[str]) -> None:
        self._characters = iter(characters)
        self._peeked: str | None = None

    def get(self) -> str | None:
        if self._peeked is not None:
            value = self._peeked
            self._peeked = None
            return value
        return next(self._characters, None)

    def peek(self) -> str | None:
        if self._peeked is None:
            self._peeked = next(self._characters, None)
        return self._peeked


def _unquote_identifier(value: str) -> str:
    if not value.startswith("`"):
        return value
    unquoted: list[str] = []
    index = 1
    while index < len(value) - 1:
        character = value[index]
        if character in {"`", "\\"} and index + 1 < len(value) - 1:
            unquoted.append(value[index + 1])
            index += 2
            continue
        unquoted.append(character)
        index += 1
    return "".join(unquoted)


def _encode_target_mysql_version(value: str) -> int:
    if type(value) is not str:
        raise LegacyBackupSanitizationError(
            "target MySQL version must be canonical major.minor.patch"
        )
    matched = _CANONICAL_MYSQL_VERSION_RE.fullmatch(value)
    if matched is None:
        raise LegacyBackupSanitizationError(
            "target MySQL version must be canonical major.minor.patch"
        )
    major, minor, patch = (int(component) for component in matched.groups())
    return major * 10_000 + minor * 100 + patch


def _mask_quoted_tokens(statement: str, *, include_identifiers: bool) -> str:
    masked: list[str] = []
    quotes = {"'", '"'}
    if include_identifiers:
        quotes.add("`")
    index = 0
    while index < len(statement):
        character = statement[index]
        if character not in quotes:
            masked.append(character)
            index += 1
            continue
        quote = character
        masked.append(" ")
        index += 1
        while index < len(statement):
            character = statement[index]
            masked.append(" ")
            index += 1
            if character == "\\" and index < len(statement):
                masked.append(" ")
                index += 1
                continue
            if character == quote:
                if index < len(statement) and statement[index] == quote:
                    masked.append(" ")
                    index += 1
                    continue
                break
    return "".join(masked)


def _consume_quoted_value(value: str, index: int) -> int:
    quote = value[index]
    index += 1
    while index < len(value):
        character = value[index]
        index += 1
        if character == "\\":
            if index >= len(value):
                return -1
            index += 1
            continue
        if character != quote:
            continue
        if index < len(value) and value[index] == quote:
            index += 1
            continue
        return index
    return -1


def _matching_parenthesis(value: str, open_index: int) -> int | None:
    depth = 0
    index = open_index
    while index < len(value):
        character = value[index]
        if character in {"'", '"', "`"}:
            index = _consume_quoted_value(value, index)
            if index < 0:
                return None
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
            if depth < 0:
                return None
        index += 1
    return None


def _validate_create_table_suffix(suffix: str) -> bool:
    index = 0
    seen_options: set[str] = set()
    while True:
        while index < len(suffix) and suffix[index].isspace():
            index += 1
        if index == len(suffix):
            return True
        matched = False
        for option_name, pattern in _CREATE_TABLE_OPTION_PATTERNS:
            option = pattern.match(suffix, index)
            if option is None:
                continue
            if option_name in seen_options:
                return False
            seen_options.add(option_name)
            index = option.end()
            matched = True
            break
        if matched:
            continue
        quoted_option = re.match(
            r"(?:COMMENT|COMPRESSION|ENCRYPTION)\s*=\s*",
            suffix[index:],
            re.IGNORECASE,
        )
        if quoted_option is None:
            return False
        option_name = quoted_option.group(0).split("=", 1)[0].strip().lower()
        if option_name in seen_options:
            return False
        index += quoted_option.end()
        if index >= len(suffix) or suffix[index] not in {"'", '"'}:
            return False
        index = _consume_quoted_value(suffix, index)
        if index < 0:
            return False
        seen_options.add(option_name)


def _skip_whitespace(value: str, index: int) -> int:
    while index < len(value) and value[index].isspace():
        index += 1
    return index


def _consume_insert_literal(value: str, index: int) -> int | None:
    index = _skip_whitespace(value, index)
    if index >= len(value):
        return None
    if value[index] in {"'", '"'}:
        result = _consume_quoted_value(value, index)
        return result if result >= 0 else None

    introducer = re.match(r"(?:_[A-Za-z0-9]+|[BNX])\s*", value[index:], re.IGNORECASE)
    if introducer is not None:
        quoted_index = index + introducer.end()
        if quoted_index < len(value) and value[quoted_index] in {"'", '"'}:
            result = _consume_quoted_value(value, quoted_index)
            return result if result >= 0 else None

    null_value = re.match(r"NULL\b", value[index:], re.IGNORECASE)
    if null_value is not None:
        return index + null_value.end()
    hex_value = re.match(r"0x[0-9A-F]+\b", value[index:], re.IGNORECASE)
    if hex_value is not None:
        return index + hex_value.end()
    number = re.match(
        r"[-+]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][-+]?[0-9]+)?\b",
        value[index:],
    )
    if number is not None:
        return index + number.end()
    return None


def _validate_insert_values(value: str) -> bool:
    index = 0
    row_count = 0
    while True:
        index = _skip_whitespace(value, index)
        if index >= len(value) or value[index] != "(":
            return False
        index += 1
        value_count = 0
        while True:
            literal_end = _consume_insert_literal(value, index)
            if literal_end is None:
                return False
            value_count += 1
            index = _skip_whitespace(value, literal_end)
            if index >= len(value):
                return False
            if value[index] == ",":
                index += 1
                continue
            if value[index] != ")":
                return False
            index += 1
            break
        if value_count == 0:
            return False
        row_count += 1
        index = _skip_whitespace(value, index)
        if index == len(value):
            return row_count > 0
        if value[index] != ",":
            return False
        index += 1


class _StatementValidator:
    def __init__(self) -> None:
        self.statement_type_counts: Counter[str] = Counter()
        self.created_tables: set[str] = set()
        self.disabled_key_tables: set[str] = set()
        self.statement_count = 0
        self.sql_mode_state = "untrusted"
        self.saw_data_statement = False

    def validate(self, statement: str) -> None:
        statement = statement.strip()
        if not statement:
            return
        self.statement_count += 1
        structural_code = _mask_quoted_tokens(statement, include_identifiers=False)
        command_code = _mask_quoted_tokens(statement, include_identifiers=True)
        first_keyword_match = re.match(r"\s*([A-Za-z]+)", command_code)
        first_keyword = first_keyword_match.group(1).upper() if first_keyword_match else ""
        if first_keyword in _META_COMMANDS:
            self._reject("client_meta_command")
        for pattern in _FORBIDDEN_CODE_PATTERNS:
            if pattern.search(command_code):
                self._reject("forbidden_server_or_file_command")

        if first_keyword == "SET":
            normalized = re.sub(r"\s+", " ", statement).strip()
            set_kind = next(
                (
                    kind
                    for kind, pattern in _SET_ALLOWLIST
                    if pattern.fullmatch(normalized)
                ),
                None,
            )
            if set_kind is None:
                self._reject("session_set_not_allowlisted")
            if set_kind == "sql_mode_normalize":
                if self.sql_mode_state != "untrusted":
                    self._reject("sql_mode_normalization_out_of_order")
                self.sql_mode_state = "normalized"
            elif set_kind == "sql_mode_restore":
                if self.sql_mode_state != "normalized" or not self.saw_data_statement:
                    self._reject("sql_mode_restore_out_of_order")
                self.sql_mode_state = "restored"
            elif self.sql_mode_state == "restored" and set_kind != "teardown":
                self._reject("session_setup_after_sql_mode_restore")
            self.statement_type_counts["set_session"] += 1
            return

        if (
            first_keyword in _DATA_STATEMENT_KEYWORDS
            and self.sql_mode_state != "normalized"
        ):
            self._reject("data_statement_without_normalized_sql_mode")

        drop = re.fullmatch(
            rf"DROP\s+TABLE\s+IF\s+EXISTS\s+({_IDENTIFIER})",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        if drop:
            table = _unquote_identifier(drop.group(1))
            self.created_tables.discard(table)
            self.disabled_key_tables.discard(table)
            self.statement_type_counts["drop_table"] += 1
            self.saw_data_statement = True
            return

        create = re.match(
            rf"CREATE\s+TABLE\s+({_IDENTIFIER})\s*\(",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        if create:
            table = _unquote_identifier(create.group(1))
            if table in self.created_tables:
                self._reject("duplicate_create_table")
            if re.search(
                rf"\bREFERENCES\s+{_IDENTIFIER}\s*\.",
                structural_code,
                re.IGNORECASE,
            ):
                self._reject("cross_schema_reference")
            open_index = create.end() - 1
            close_index = _matching_parenthesis(statement, open_index)
            if close_index is None:
                self._reject("create_table_definition_not_closed")
            if not _validate_create_table_suffix(statement[close_index + 1 :]):
                self._reject("create_table_suffix_not_allowlisted")
            self.created_tables.add(table)
            self.statement_type_counts["create_table"] += 1
            self.saw_data_statement = True
            return

        alter = re.fullmatch(
            rf"ALTER\s+TABLE\s+({_IDENTIFIER})\s+(DISABLE|ENABLE)\s+KEYS",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        if alter:
            table = _unquote_identifier(alter.group(1))
            action = alter.group(2).upper()
            if table not in self.created_tables:
                self._reject("alter_keys_table_not_created")
            if action == "DISABLE":
                if table in self.disabled_key_tables:
                    self._reject("alter_keys_already_disabled")
                self.disabled_key_tables.add(table)
                self.statement_type_counts["alter_disable_keys"] += 1
            else:
                if table not in self.disabled_key_tables:
                    self._reject("alter_keys_not_disabled")
                self.disabled_key_tables.remove(table)
                self.statement_type_counts["alter_enable_keys"] += 1
            self.saw_data_statement = True
            return

        insert = re.match(
            rf"INSERT\s+INTO\s+({_IDENTIFIER})\s+VALUES\s*",
            statement,
            re.IGNORECASE | re.DOTALL,
        )
        if insert:
            table = _unquote_identifier(insert.group(1))
            if table not in self.created_tables:
                self._reject("insert_table_not_created")
            if not _validate_insert_values(statement[insert.end() :]):
                self._reject("insert_values_not_allowlisted")
            self.statement_type_counts["insert"] += 1
            self.saw_data_statement = True
            return

        lock = re.fullmatch(r"LOCK\s+TABLES\s+(.+)", statement, re.IGNORECASE | re.DOTALL)
        if lock:
            entries = [entry.strip() for entry in lock.group(1).split(",")]
            if not entries:
                self._reject("lock_tables_empty")
            for entry in entries:
                match = re.fullmatch(
                    rf"({_IDENTIFIER})\s+(?:READ(?:\s+LOCAL)?|WRITE)",
                    entry,
                    re.IGNORECASE,
                )
                if match is None or _unquote_identifier(match.group(1)) not in self.created_tables:
                    self._reject("lock_table_not_created")
            self.statement_type_counts["lock_tables"] += 1
            self.saw_data_statement = True
            return

        if re.fullmatch(r"UNLOCK\s+TABLES", statement, re.IGNORECASE):
            self.statement_type_counts["unlock_tables"] += 1
            self.saw_data_statement = True
            return
        if re.fullmatch(r"START\s+TRANSACTION", statement, re.IGNORECASE):
            self.statement_type_counts["start_transaction"] += 1
            self.saw_data_statement = True
            return
        if re.fullmatch(r"COMMIT", statement, re.IGNORECASE):
            self.statement_type_counts["commit"] += 1
            self.saw_data_statement = True
            return
        self._reject("statement_not_allowlisted")

    def finish(self) -> None:
        if self.disabled_key_tables:
            self._reject("alter_keys_not_reenabled")
        if self.sql_mode_state == "normalized":
            self._reject("sql_mode_not_restored")

    def _reject(self, reason: str) -> None:
        raise LegacyBackupSanitizationError(
            f"unsafe MySQL dump statement at index {self.statement_count}: {reason}"
        )


class _StreamingParser:
    def __init__(
        self,
        characters: Iterable[str],
        *,
        target_mysql_version_code: int,
        validator: _StatementValidator | None = None,
        bounded_executable_body: bool = False,
    ) -> None:
        self.stream = _CharacterStream(characters)
        self.statement: list[str] = []
        self.validator = validator or _StatementValidator()
        self.owns_validator = validator is None
        self.target_mysql_version_code = target_mysql_version_code
        self.bounded_executable_body = bounded_executable_body
        self.executable_comment_count = 0

    def parse(self) -> None:
        while (character := self.stream.get()) is not None:
            if character in {"'", '"', "`"}:
                self._consume_quoted(character)
                continue
            if character == "\\":
                raise LegacyBackupSanitizationError("MySQL client backslash commands are forbidden")
            if character == "#":
                self._consume_line_comment()
                continue
            if character == "-" and self.stream.peek() == "-":
                self.stream.get()
                third = self.stream.peek()
                if third is None or third.isspace():
                    self._consume_line_comment()
                    continue
                self.statement.extend(("-", "-"))
                continue
            if character == "/" and self.stream.peek() == "*":
                self.stream.get()
                self._consume_block_comment()
                continue
            if character == ";":
                self.validator.validate("".join(self.statement))
                self.statement.clear()
                continue
            self.statement.append(character)
        self.validator.validate("".join(self.statement))
        if self.owns_validator:
            self.validator.finish()

    def _consume_quoted(self, quote: str) -> None:
        self.statement.append(quote)
        while (character := self.stream.get()) is not None:
            self.statement.append(character)
            if character == "\\":
                escaped = self.stream.get()
                if escaped is None:
                    raise LegacyBackupSanitizationError("unterminated quoted string")
                self.statement.append(escaped)
                continue
            if character != quote:
                continue
            if self.stream.peek() == quote:
                self.statement.append(self.stream.get() or "")
                continue
            return
        raise LegacyBackupSanitizationError("unterminated quoted string")

    def _consume_line_comment(self) -> None:
        while (character := self.stream.get()) is not None:
            if character in {"\n", "\r"}:
                self.statement.append(" ")
                return
        if self.bounded_executable_body:
            raise LegacyBackupSanitizationError(
                "unterminated executable comment body line comment"
            )

    def _consume_block_comment(self) -> None:
        marker = self.stream.peek()
        executable = marker == "!"
        if executable:
            self.stream.get()
            self.executable_comment_count += 1
        body: list[str] = []
        while (character := self.stream.get()) is not None:
            if character == "*" and self.stream.peek() == "/":
                self.stream.get()
                if executable:
                    value = "".join(body)
                    gate: int | None = None
                    if value and value[0].isdigit():
                        gate_match = re.match(r"([0-9]{5,6})(?![0-9])", value)
                        if gate_match is None:
                            raise LegacyBackupSanitizationError(
                                "executable comment version gate must have 5 or 6 digits"
                            )
                        gate = int(gate_match.group(1))
                        value = value[gate_match.end() :]
                    if gate is None or gate <= self.target_mysql_version_code:
                        if "".join(self.statement).strip():
                            raise LegacyBackupSanitizationError(
                                "inline executable comment fragments are not supported"
                            )
                        body_parser = _StreamingParser(
                            value,
                            target_mysql_version_code=self.target_mysql_version_code,
                            validator=self.validator,
                            bounded_executable_body=True,
                        )
                        body_parser.parse()
                        self.executable_comment_count += (
                            body_parser.executable_comment_count
                        )
                        self.statement.append(" ")
                    else:
                        self.statement.append(" ")
                else:
                    self.statement.append(" ")
                return
            body.append(character)
        raise LegacyBackupSanitizationError("unterminated block comment")


def scan_mysql_dump(
    stream: BinaryIO,
    *,
    expected_backup_sha256: str,
    target_mysql_version: str,
    chunk_size: int = 64 * 1024,
) -> dict[str, Any]:
    """Validate one MySQL dump stream without returning SQL text or row data."""

    if type(expected_backup_sha256) is not str or _LOWER_SHA256_RE.fullmatch(
        expected_backup_sha256
    ) is None:
        raise LegacyBackupSanitizationError(
            "expected backup SHA-256 must be 64 lowercase hexadecimal characters"
        )
    if type(chunk_size) is not int or chunk_size <= 0:
        raise LegacyBackupSanitizationError("chunk size must be a positive integer")
    target_mysql_version_code = _encode_target_mysql_version(target_mysql_version)
    read = getattr(stream, "read", None)
    if not callable(read):
        raise LegacyBackupSanitizationError("backup stream must provide read()")

    digest = hashlib.sha256()
    size_bytes = 0
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")

    def characters() -> Iterable[str]:
        nonlocal size_bytes
        try:
            while True:
                chunk = read(chunk_size)
                if chunk in {b"", ""}:
                    break
                if type(chunk) is not bytes:
                    raise LegacyBackupSanitizationError("backup stream must yield bytes")
                digest.update(chunk)
                size_bytes += len(chunk)
                yield from decoder.decode(chunk, final=False)
            yield from decoder.decode(b"", final=True)
        except UnicodeDecodeError as exc:
            raise LegacyBackupSanitizationError("backup is not valid UTF-8") from exc

    parser = _StreamingParser(
        characters(),
        target_mysql_version_code=target_mysql_version_code,
    )
    parser.parse()
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_backup_sha256:
        raise LegacyBackupSanitizationError("backup SHA-256 does not match expected digest")
    return {
        "backup_sha256": actual_sha256,
        "size_bytes": size_bytes,
        "statement_count": parser.validator.statement_count,
        "statement_type_counts": dict(sorted(parser.validator.statement_type_counts.items())),
        "created_table_count": len(parser.validator.created_tables),
        "executable_comment_count": parser.executable_comment_count,
        "target_mysql_version": target_mysql_version,
    }
