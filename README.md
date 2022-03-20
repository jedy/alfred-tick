### 说明

**从macOS 12.3 Monterey开始，系统不再提供python 2了，所以升级为使用python 3。老版本的mac请使用1.6。**

脚本使用的python，测试的环境是2.7，其他的版本没试过。
适用于中文版的[滴答清单](https://www.dida365.com), 英文版应该也可以，需要把tick.py中的url改成英文版的。

### 安装

   * 安装所需的python模块
       - `pip install tzlocal`
   * 导入tick.alfredworkflow
   * alfred中输入"tick_login 用户名<空格>密码"登陆，登陆后会把需要的cookie和收集箱的id保存到~/.ticktick文件中

### 使用

  ![screen](https://github.com/jedy/alfred-tick/blob/master/screenshot.png?raw=true)
  
   * 输入"tick 任务 [日期] [时间]"，日期和时间都可以不写
   * 日期支持下面这些形式
       - tomorrow|tmr
       - mon|tue|wed|thu|fri|sat|sun
       - every mon|tue|wed|thu|fri|sat|sun，每周重复
       - next mon|tue|wed|thu|fri|sat|sun
       - month-day
       - every month-day, 每月重复
       - every，每天重复
   * 时间支持"hour:minute"的形式

### Description

**From macOS 12.3 Monterey, system doesn't include python 2, so it's upgraded to python 3。Please use 1.6 on old versions of mac.**

This workflow uses python 2.7. Haven't tested in other version.
It's for [滴答清单](https://www.dida365.com). 
If you use [Ticktick](https://www.ticktick.com), please checkout branch "ticktick".
However, since I don't have account of ticktick to test, it may not work correctly.

### Install

   * install python package
       * `pip install tzlocal`
   * import tick.alfredworkflow
   * input "tick_login username <space> password" in alfred to login. Cookie and inbox id will be saved in ~/.ticktick.

### Usage

   * input "tick task [date] [time]", `date` and `time` can be omitted
   * date supports following formats:
       - tomorrow|tmr
       - mon|tue|wed|thu|fri|sat|sun
       - every mon|tue|wed|thu|fri|sat|sun，repeat every week
       - next mon|tue|wed|thu|fri|sat|sun
       - month-day
       - every month-day, repeat every month
       - every，repeat everyday
   * time should be inputed as "hour:minute"
