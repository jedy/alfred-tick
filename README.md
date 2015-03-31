### 说明

脚本使用的python，测试的环境是2.7，其他的版本没试过。
适用于中文版的[滴答清单](https://www.dida365.com), 英文版应该也可以，需要把tick.py中的url改成英文版的。

### 安装

   * 安装所需的python模块
       - `pip install tzlocal alfred`
   * 导入tick.alfredworkflow
   * alfred中输入"tick_login 用户名<空格>密码"登陆，登陆后会把需要的cookie和收集箱的id保存到~/.ticktick文件中

### 使用
   * 输入"tick 任务 [日期] [时间]"，日期和时间都可以不写
   * 日期支持下面这些形式
       - tomorrow
       - mon|tue|wed|thu|fri|sat|sun
       - every mon|tue|wed|thu|fri|sat|sun，每周重复
       - next mon|tue|wed|thu|fri|sat|sun
       - month-day
       - every month-day, 每月重复
       - every，每天重复
   * 时间支持"hour:minute"的形式

