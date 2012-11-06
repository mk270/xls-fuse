
import xlrd

class Spreadsheet(object):
    def __init__(self, filename):
        self.wb = xlrd.open_workbook(filename)

    def tree(self):
        tmp = { "sheet": {} }

        for name in self.wb.sheet_names():
            tmp["sheet"][name] = { "row": {} }

            sheet = self.wb.sheet_by_name(name)
            for row in range(0, sheet.nrows):
                row_id = str(row)
                tmp["sheet"][name]["row"][row_id] = { "col": {} }

                for col in range(0, sheet.ncols):
                    col_id = str(col)
                    value = sheet.cell(row, col).value

                    if isinstance(value, unicode):
                        value = value.encode('utf-8')

                    value = str(value)
                    if not value.endswith("\n"):
                        value += "\n"

                    tmp["sheet"][name]["row"][row_id]["col"][col_id] = value

        return tmp
            
