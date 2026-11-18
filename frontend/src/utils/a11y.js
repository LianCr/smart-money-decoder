// 让非 <button> 的可点击块（内部含块级元素，不能换成 button）也能被键盘操作：
// Tab 可聚焦、Enter/Space 触发、读屏知道它是可展开的按钮。
export function disclosureProps(open, toggle) {
  return {
    role: "button",
    tabIndex: 0,
    "aria-expanded": open,
    onClick: toggle,
    onKeyDown: (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    },
  };
}
