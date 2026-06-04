"""Feishu Sheets integration for reading tasks and writing results."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import lark_oapi as lark
from lark_oapi.api.sheets.v3 import (
	GetSpreadsheetRequest,
	QuerySpreadsheetSheetRequest,
)

logger = logging.getLogger(__name__)

# Default column mapping for task rows (0-indexed column positions).
# Adjust these indices to match the actual spreadsheet layout.
DEFAULT_COLUMN_MAP: dict[str, int] = {
	"platform": 0,
	"product_name": 1,
	"new_price": 2,
	"action": 3,
	"instruction": 4,
}


class FeishuSheet:
	"""Reads task rows from and writes results back to Feishu spreadsheets."""

	def __init__(self, client: lark.Client) -> None:
		self._client = client

	# ------------------------------------------------------------------
	# Public API
	# ------------------------------------------------------------------

	async def read_tasks_from_sheet(
		self,
		spreadsheet_token: str,
		sheet_id: str,
	) -> list[dict[str, Any]]:
		"""Read rows from a Feishu spreadsheet and return them as task dicts.

		Each row becomes a dict keyed by the column mapping.  The first row
		is treated as a header row and skipped.  Empty rows are omitted.

		Args:
			spreadsheet_token: The token identifying the spreadsheet.
			sheet_id: The sheet (tab) ID within the spreadsheet.

		Returns:
			A list of dicts, one per data row.
		"""
		try:
			# First determine how many rows contain data via sheet metadata.
			sheet_meta = await self._get_sheet_properties(spreadsheet_token, sheet_id)
			row_count: int = sheet_meta.get("row_count", 1000)

			# Read all data in one batch (columns A through the last mapped column).
			max_col_index = max(DEFAULT_COLUMN_MAP.values())
			end_col_letter = _index_to_column_letter(max_col_index)
			read_range = f"{sheet_id}!A2:{end_col_letter}{row_count}"

			values = await self._read_range(spreadsheet_token, read_range)

			tasks: list[dict[str, Any]] = []
			for row in values:
				if not row or all(cell is None or cell == "" for cell in row):
					continue
				task: dict[str, Any] = {}
				for key, col_idx in DEFAULT_COLUMN_MAP.items():
					if col_idx < len(row):
						task[key] = row[col_idx]
				tasks.append(task)

			logger.info(
				"Read %d task rows from spreadsheet %s sheet %s",
				len(tasks),
				spreadsheet_token,
				sheet_id,
			)
			return tasks

		except Exception:
			logger.exception(
				"Failed to read tasks from spreadsheet %s sheet %s",
				spreadsheet_token,
				sheet_id,
			)
			raise

	async def write_result_to_sheet(
		self,
		spreadsheet_token: str,
		sheet_id: str,
		row_index: int,
		result: dict[str, Any],
	) -> None:
		"""Write an execution result back to a specific row in the sheet.

		Result columns are written after the task columns.  For example,
		if the task columns end at column E, results start at column F.

		Args:
			spreadsheet_token: The token identifying the spreadsheet.
			sheet_id: The sheet (tab) ID within the spreadsheet.
			row_index: The 1-based row number to write to (matching sheet rows).
			result: Dict with keys such as ``status`` and ``message``.
		"""
		try:
			# Result columns start right after the last task column.
			max_col_index = max(DEFAULT_COLUMN_MAP.values())
			result_start_col = _index_to_column_letter(max_col_index + 1)

			status = result.get("status", "")
			message = result.get("message", "")

			write_range = f"{sheet_id}!{result_start_col}{row_index}"
			values = [[status, message]]

			await self._write_range(spreadsheet_token, write_range, values)

			logger.info(
				"Wrote result to spreadsheet %s sheet %s row %d",
				spreadsheet_token,
				sheet_id,
				row_index,
			)

		except Exception:
			logger.exception(
				"Failed to write result to spreadsheet %s sheet %s row %d",
				spreadsheet_token,
				sheet_id,
				row_index,
			)
			raise

	async def get_sheet_meta(self, spreadsheet_token: str) -> dict[str, Any]:
		"""Get spreadsheet metadata (title, sheets list, properties).

		Args:
			spreadsheet_token: The token identifying the spreadsheet.

		Returns:
			A dict containing spreadsheet metadata.
		"""
		try:
			request = GetSpreadsheetRequest.builder().spreadsheet_token(spreadsheet_token).build()

			response = await asyncio.to_thread(
				self._client.sheets.v3.spreadsheet.get,
				request,
			)

			if not response.success():
				raise RuntimeError(
					f"Failed to get spreadsheet meta: code={response.code}, msg={response.msg}"
				)

			spreadsheet = response.data.spreadsheet
			meta: dict[str, Any] = {
				"title": spreadsheet.title if spreadsheet else "",
				"spreadsheet_token": spreadsheet_token,
			}

			# Fetch sheet (tab) list.
			sheets = await self._list_sheets(spreadsheet_token)
			meta["sheets"] = sheets

			logger.info(
				"Got metadata for spreadsheet %s: %s",
				spreadsheet_token,
				meta.get("title"),
			)
			return meta

		except Exception:
			logger.exception("Failed to get metadata for spreadsheet %s", spreadsheet_token)
			raise

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	async def _list_sheets(self, spreadsheet_token: str) -> list[dict[str, Any]]:
		"""Return the list of sheets (tabs) in a spreadsheet."""
		request = (
			QuerySpreadsheetSheetRequest.builder()
			.spreadsheet_token(spreadsheet_token)
			.build()
		)

		response = await asyncio.to_thread(
			self._client.sheets.v3.spreadsheet_sheet.query,
			request,
		)

		if not response.success():
			raise RuntimeError(
				f"Failed to list sheets: code={response.code}, msg={response.msg}"
			)

		sheets: list[dict[str, Any]] = []
		if response.data and response.data.sheets:
			for sheet in response.data.sheets:
				sheets.append({
					"sheet_id": sheet.sheet_id,
					"title": sheet.title,
					"index": sheet.index,
					"row_count": sheet.grid_properties.row_count if sheet.grid_properties else None,
					"column_count": sheet.grid_properties.column_count if sheet.grid_properties else None,
				})

		return sheets

	async def _get_sheet_properties(
		self,
		spreadsheet_token: str,
		sheet_id: str,
	) -> dict[str, Any]:
		"""Get properties for a specific sheet tab."""
		sheets = await self._list_sheets(spreadsheet_token)
		for sheet in sheets:
			if sheet.get("sheet_id") == sheet_id:
				return sheet

		# If sheet_id not found, return a safe default and log a warning.
		logger.warning(
			"Sheet %s not found in spreadsheet %s, using defaults",
			sheet_id,
			spreadsheet_token,
		)
		return {"row_count": 1000, "column_count": 20}

	async def _read_range(
		self,
		spreadsheet_token: str,
		range_str: str,
	) -> list[list[Any]]:
		"""Read cell values from a range using the Sheets v2 HTTP API.

		The lark-oapi SDK may not expose a typed v2 values.get builder,
		so we call the raw HTTP endpoint through the client's transport.
		"""
		url = (
			f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
			f"/values/{range_str}"
		)

		def _do_request() -> Any:
			# lark.Client exposes a ``request`` method for raw HTTP calls.
			req = lark.RawRequest.build(
				"GET",
				url,
				None,
				None,
				None,
			)
			return self._client.request(req)

		raw_response = await asyncio.to_thread(_do_request)

		if raw_response.status_code != 200:
			raise RuntimeError(
				f"Failed to read range {range_str}: "
				f"status={raw_response.status_code}, body={raw_response.content}"
			)

		import json

		body = json.loads(raw_response.content)
		if body.get("code") != 0:
			raise RuntimeError(
				f"Failed to read range {range_str}: "
				f"code={body.get('code')}, msg={body.get('msg')}"
			)

		value_range = body.get("data", {}).get("valueRange", {})
		values: list[list[Any]] = value_range.get("values", [])
		return values

	async def _write_range(
		self,
		spreadsheet_token: str,
		range_str: str,
		values: list[list[Any]],
	) -> None:
		"""Write cell values to a range using the Sheets v2 HTTP API."""
		url = (
			f"/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
			f"/values"
		)

		import json

		body = json.dumps({
			"valueRange": {
				"range": range_str,
				"values": values,
			}
		}).encode("utf-8")

		def _do_request() -> Any:
			req = lark.RawRequest.build(
				"PUT",
				url,
				None,
				body,
				None,
			)
			return self._client.request(req)

		raw_response = await asyncio.to_thread(_do_request)

		if raw_response.status_code != 200:
			raise RuntimeError(
				f"Failed to write range {range_str}: "
				f"status={raw_response.status_code}, body={raw_response.content}"
			)

		resp_body = json.loads(raw_response.content)
		if resp_body.get("code") != 0:
			raise RuntimeError(
				f"Failed to write range {range_str}: "
				f"code={resp_body.get('code')}, msg={resp_body.get('msg')}"
			)


def _index_to_column_letter(index: int) -> str:
	"""Convert a 0-based column index to a spreadsheet column letter.

	Examples: 0 -> 'A', 1 -> 'B', 25 -> 'Z', 26 -> 'AA'.
	"""
	result = ""
	while True:
		result = chr(ord("A") + index % 26) + result
		index = index // 26 - 1
		if index < 0:
			break
	return result
