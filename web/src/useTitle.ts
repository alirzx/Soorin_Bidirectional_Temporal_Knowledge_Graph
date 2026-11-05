/* 网页标题系统：`{域} | {页面}`，品牌在前（产品决策；代价是多标签截断后同前缀）。
   域：Soorin TKG（主应用）/ Soorin TKG Charter（文档）/ Soorin TKG Persona（账户）。 */
import { useEffect } from "react";

export function usePageTitle(...parts: (string | null | undefined)[]) {
  const title = parts.filter(Boolean).join(" | ");
  useEffect(() => {
    if (title) document.title = title;
  }, [title]);
}
