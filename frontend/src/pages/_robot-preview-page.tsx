import { RobotCharacter, type RobotState } from '@/components/robot/robot-character'

const STATES: RobotState[] = ['idle', 'walk', 'working', 'celebrate', 'error', 'shield', 'sad']

export function RobotPreviewPage() {
  return (
    <div className="flex min-h-screen flex-wrap gap-8 bg-background p-8">
      {STATES.map((s) => (
        <div key={s} className="flex flex-col items-center gap-2 rounded-lg border border-border bg-surface p-6">
          <RobotCharacter state={s} scale={1.3} carrying={s === 'idle' ? { label: 'policy.pdf' } : null} />
          <span className="text-sm text-foreground">{s}</span>
        </div>
      ))}
    </div>
  )
}
