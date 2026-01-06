## OceanBase

**Author:** oceanbase  
**Version:** 0.0.2
**Type:** tool  
**Repo:** https://github.com/oceanbase/dify-plugin-oceanbase

### 描述

本插件用于查询 OceanBase 数据库，包含多个工具来帮助用户与 OceanBase 数据库进行交互。

### 工具介绍

#### 1. 执行 SQL (Execute SQL)

- **功能**: 在现有的 OceanBase 数据库中执行 SQL 查询
- **用途**: 直接执行 SELECT、SHOW 或 WITH 开头的 SQL 语句
- **输出格式**: 支持 JSON、CSV、YAML、Markdown、Excel、HTML 等多种格式
- **安全限制**: 仅支持查询类语句，确保数据库安全

#### 2. 获取表结构 (Get Table Schema)

- **功能**: 从数据库中获取表结构信息
- **用途**: 为 LLM 提供数据库上下文，帮助理解表结构
- **灵活性**: 可指定特定表或获取所有表的结构信息
- **应用场景**: 在生成 SQL 查询前了解数据库结构

#### 3. 文本转 SQL (Text to SQL)

- **功能**: 使用 LLM 将自然语言查询转换为 SQL 语句
- **用途**: 让用户可以用自然语言描述查询需求，自动生成对应的 SQL
- **智能性**: 基于数据库上下文和表结构信息生成准确的 SQL
- **模型选择**: 支持选择不同的大语言模型进行转换

### 使用说明

1. **数据库连接**: 配置 OceanBase 数据库连接信息
2. **选择工具**: 根据需求选择合适的工具
3. **执行查询**: 通过自然语言或直接 SQL 进行数据查询
4. **获取结果**: 以指定格式获取查询结果

### 注意事项

- 该插件仅支持查询操作，不支持数据修改
- 建议使用只读数据库账户以确保安全性
- 支持多种输出格式，可根据需要选择

### 参考

本插件参考了 [dify-plugin-database](https://github.com/hjlarry/dify-plugin-database)，并针对 OceanBase 数据库进行了适配和优化。
