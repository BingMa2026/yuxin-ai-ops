// 数量、有效期由结构化字段展示；兼容历史权益文案中的旧数值。
export function planBenefits(benefits: readonly string[]): string[] {
  return benefits.filter((benefit) => {
    const text = benefit.replace(/[\s,，]/g, "");
    return (
      !/^\d+(?:\.\d+)?[万亿]?(?:点|个)?(?:算力)?积分$/.test(text) &&
      !/^(?:积分)?有效期[:：]?\d+天$/.test(text)
    );
  });
}
