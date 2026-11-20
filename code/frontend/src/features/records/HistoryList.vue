<script setup lang="ts">
import { NEmpty, NButton, NTag } from 'naive-ui';
import { History } from 'lucide-vue-next';
import { levelLabels } from '../../types';
import type { HistoryPage } from '../../types';
defineProps<{ history: HistoryPage; busy: boolean }>();
const emit = defineEmits<{ report: [key: string]; more: [] }>();
</script><template>
              <NEmpty v-if="!history.items.length" description="完成第一道题后，记录会出现在这里" class="empty" />
              <section v-else class="panel">
                <article v-for="a in history.items" :key="a.id" class="history-row">
                  <span class="task-icon">
                    <History :size="20" />
                  </span>
                  <div>
                    <h3>{{ a.question_key }} ·
                      <NTag type="success">
                        {{ levelLabels[a.level] }}
                      </NTag>
                    </h3>
                    <p>
                      {{
                        new Date(a.created_at * 1000).toLocaleString("zh-CN")
                      }}
                      · 题目版本 v{{ a.question_version
                      }}{{
                        a.content_status === "retired"
                          ? " · 已停用，不计入当前诊断"
                          : ""
                      }}
                    </p>
                    <p v-if="a.retirement_reason">
                      停用原因：{{ a.retirement_reason }}
                    </p>
                    <NButton text size="tiny" @click="emit('report', a.question_key)">报告答案 / 解析 / 标签问题</NButton>
                    <details class="history-details">
                      <summary>查看本次作答</summary>
                      <p>
                        你的选项：{{ a.selected }}<br />正确答案：{{ a.answer
                        }}<br />{{ a.explanation }}
                      </p>
                    </details>
                  </div>
                  <NTag :type="a.correct ? 'success' : 'warning'" :bordered="false">{{ a.correct ? "回答正确" : "需要巩固" }}
                  </NTag>
                </article>
                <NButton v-if="history.items.length < history.total" block secondary :loading="busy"
                  @click="emit('more')">加载更多记录</NButton>
              </section>
</template>