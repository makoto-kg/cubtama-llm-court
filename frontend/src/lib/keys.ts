/**
 * 台詞を送るキー(Enter・Space)か。重ねて出したダイアログ(確認・証拠品ファイルなど)が開いているときは、
 * そちらのボタンの操作を優先して、裏の台詞は送らない。
 */
export function isAdvanceKey(e: Pick<KeyboardEvent, "key">, doc: Pick<Document, "querySelector"> = document): boolean {
  if (e.key !== "Enter" && e.key !== " ") return false;
  return doc.querySelector('[aria-modal="true"]') === null;
}
