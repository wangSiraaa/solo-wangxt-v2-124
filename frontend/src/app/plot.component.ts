import {
  Component, ElementRef, Input, OnChanges, OnDestroy, ViewChild,
} from '@angular/core';
import Plotly from 'plotly.js-dist-min';

/** 极简 Plotly 封装：输入 traces/layout，直接 newPlot/react。 */
@Component({
  selector: 'app-plot',
  standalone: true,
  template: `<div #host [style.height.px]="height"></div>`,
})
export class PlotComponent implements OnChanges, OnDestroy {
  @Input() traces: any[] = [];
  @Input() layout: any = {};
  @Input() height = 500;

  @ViewChild('host', { static: true }) host!: ElementRef<HTMLDivElement>;

  private drawn = false;

  ngOnChanges(): void {
    if (!this.host) return;
    const layout = {
      autosize: true,
      margin: { l: 60, r: 20, t: 30, b: 50 },
      font: { family: 'Segoe UI, PingFang SC, sans-serif', size: 12 },
      ...this.layout,
    };
    const config = { responsive: true, displaylogo: false };
    if (!this.drawn) {
      Plotly.newPlot(this.host.nativeElement, this.traces, layout, config);
      this.drawn = true;
    } else {
      Plotly.react(this.host.nativeElement, this.traces, layout, config);
    }
  }

  ngOnDestroy(): void {
    if (this.drawn) Plotly.purge(this.host.nativeElement);
  }
}
