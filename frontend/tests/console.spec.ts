import { test, expect } from "@playwright/test";

test("login, live frame, receipt, event replay, faults, reconnect, responsive layout", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  const loginButton = page.getByRole("button", { name: "操作员登录" });
  const passwordField = page.getByLabel("访问密码");
  await expect(passwordField.or(loginButton)).toBeVisible();
  if (await loginButton.isVisible()) await loginButton.click();
  await passwordField.fill(process.env.DEMO_PASSWORD!);
  await page.getByRole("button", { name: "进入控制台" }).click();
  await expect(page.getByText("已连接", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: /模拟观测帧/ })).toBeVisible();
  await page.getByRole("button", { name: "请求模拟暂停" }).click();
  await expect(
    page.getByText("模拟执行已确认", { exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "实验会话", exact: true }).click();
  await page.getByRole("button", { name: "打开回放" }).first().click();
  await expect(page.getByText("HISTORY / 只读")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "请求模拟暂停" }),
  ).toBeDisabled();
  await page.getByRole("slider", { name: "回放帧" }).fill("0");
  const frame = await page
    .getByRole("img", { name: /模拟观测帧/ })
    .getAttribute("src");
  await page.waitForTimeout(1200);
  expect(
    await page.getByRole("img", { name: /模拟观测帧/ }).getAttribute("src"),
  ).toBe(frame);
  await page.getByRole("button", { name: "返回实时" }).click();
  const event = page.locator(".event-list button").first();
  const eventId = await event.getAttribute("data-event-id");
  const fid = await event.getAttribute("data-frame");
  await page.locator(`[data-event-id="${eventId}"]`).click();
  await expect(
    page.getByRole("img", { name: `模拟观测帧 ${fid}`, exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "算法管理", exact: true }).click();
  await page.getByLabel("action-consistency 模拟状态").selectOption("timeout");
  await page.getByRole("button", { name: "实时观察", exact: true }).click();
  await expect(
    page.locator(".algorithm-cards").getByText("超时", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "算法管理", exact: true }).click();
  await page.getByLabel("action-consistency 模拟状态").selectOption("normal");
  await page.getByRole("button", { name: "断开网页连接并验证重连" }).click();
  await expect(
    page.getByText("断开 · 自动重连", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("已连接", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "实时观察", exact: true }).click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.mouse.move(0, 0);
  await page.screenshot({
    path: "../docs/planning/console-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "../docs/planning/console-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
