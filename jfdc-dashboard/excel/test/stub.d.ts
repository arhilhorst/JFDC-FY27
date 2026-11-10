declare namespace ExcelScript {
  interface Workbook { getWorksheet(n: string): Worksheet | undefined; addWorksheet(n: string): Worksheet; }
  interface Worksheet { delete(): void; getUsedRange(v?: boolean): Range | undefined; getRangeByIndexes(a: number, b: number, c: number, d: number): Range; getRange(a: string): Range; getFreezePanes(): { freezeRows(n: number): void }; getAutoFilter(): { apply(r: Range): void }; activate(): void; }
  interface Range { getValues(): (string | number | boolean)[][]; setValues(v: (string | number | boolean)[][]): void; setValue(v: string | number): void; getValue(): string | number | boolean; setFormula(f: string): void; getRowCount(): number; getColumnCount(): number; getRowIndex(): number; getColumnIndex(): number; getFormat(): RangeFormat; addConditionalFormat(t: ConditionalFormatType): { getTextComparison(): { setRule(r: { operator: ConditionalTextOperator; text: string }): void; getFormat(): RangeFormat } }; }
  interface RangeFormat { getFont(): { setBold(b: boolean): void; setColor(c: string): void }; getFill(): { setColor(c: string): void }; setColumnWidth(n: number): void; setWrapText(b: boolean): void; }
  enum ConditionalFormatType { containsText }
  enum ConditionalTextOperator { contains }
}
declare function require(n: string): any;
declare const process: any;
