- 修复 PDF 导入时报错：

  文件解析失败：
  TypeError:
  import_pdf() takes 3 positional arguments but 4 were given

  要求先阅读 CLAUDE.md、prompt.md、docs 中关于导题、文件解析、FastAPI 路由、service 层、异步任务相关文档，再分析当前调用链，定位为什么 import_pdf() 参数数量不匹配。

  ========================
  【问题分析要求】
  ========================

  当前错误说明：

  函数定义与实际调用参数数量不一致。

  很可能存在以下情况之一：

  1. import_pdf() 函数签名已修改
     但调用方仍使用旧参数

  2. class method 缺少 self
     或被错误当作实例方法调用

  3. FastAPI dependency injection
     自动传入额外参数

  4. celery/background task
     包装时参数变化

  5. route → service → parser
     多层透传时参数错位

  6. async/sync 改造后签名不一致

  7. parser registry / strategy pattern
     调用接口未统一

  ========================
  【必须排查】
  ========================

  检查以下内容：

  1. import_pdf 定义位置
     - parser/pdf.py
     - services/import_service.py
     - utils/pdf_importer.py
     - 或其他相关模块

  2. 所有 import_pdf 调用位置
     全局搜索：
     - import_pdf(
     - await import_pdf(
     - parser.import_pdf(
     - self.import_pdf(

  3. 检查函数签名：

  例如：

  错误情况：
  def import_pdf(file, subject):

  实际调用：
  import_pdf(file, subject, user_id)

  或者：

  def import_pdf(self, file, subject):

  但被当作普通函数调用。

  4. 检查：
     - staticmethod
     - classmethod
     - dependency injection
     - background task wrapper
     - partial()
     - callback

  ========================
  【修复要求】
  ========================

  1. 统一 import_pdf 调用接口
     所有调用方参数一致

  2. 明确函数职责：
     - 文件读取
     - PDF OCR
     - 题目解析
     - 标准化
     - 入库

  避免一个函数承担全部逻辑。

  3. 如果需要新增参数：
     - 使用 keyword arguments
     - 避免位置参数错位

  推荐：

  def import_pdf(
      file_path: str,
      subject: str,
      *,
      user_id: int | None = None,
      options: dict | None = None,
  ):

  避免：

  import_pdf(a, b, c, d)

  4. 增加参数校验
     在入口层明确报错：
     - 缺少参数
     - 参数类型错误
     - 空文件
     - 非 PDF 文件

  5. 修复所有调用链：
     route
     → service
     → parser
     → task
     → repository

  确保参数数量一致。

  ========================
  【测试要求】
  ========================

  新增测试：

  1. PDF 导入单元测试
  2. service 调用测试
  3. API 上传测试
  4. async/background task 测试
  5. 空 PDF 测试
  6. 非 PDF 文件测试

  验证：

  - 微信小程序上传正常
  - 后端 API 正常
  - 不再出现：
    TypeError: import_pdf() takes 3 positional arguments but 4 were given
  - 导入后题目成功进入审核区
  - 批量导入正常
  - 不影响 Word/TXT/PDF 其他解析器

  ========================
  【最终输出】
  ========================

  完成后输出：

  1. 根因分析
  2. import_pdf 原签名
  3. 修复后签名
  4. 所有修改的调用点
  5. 修改文件列表
  6. 测试结果
  7. 是否影响旧接口
  8. 是否需要迁移
